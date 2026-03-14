"""
GitHub Assistant MCP Server
============================

This is the main entry point for the MCP server.

HOW MCP WORKS (quick recap):
  1. Claude Desktop (the MCP Host) launches this script as a subprocess.
  2. It communicates with us over stdio using JSON-RPC 2.0 messages.
  3. On startup, Claude asks "what tools do you have?" → tools/list
  4. We respond with our tool schemas (name, description, input parameters).
  5. During a conversation, Claude decides to call a tool → tools/call
  6. We run the function, hit GitHub's API, and return the result as text.
  7. Claude uses that result to answer the user's question.

WHY FastMCP?
  The raw MCP SDK requires you to manually write JSON-RPC handlers.
  FastMCP is a higher-level wrapper that turns Python functions into MCP tools
  automatically — similar to how FastAPI turns functions into HTTP endpoints.
  The @mcp.tool() decorator does all the schema generation for you.

IMPORTANT — STDIO LOGGING RULE:
  This server uses stdio transport (stdin/stdout for JSON-RPC messages).
  NEVER use print() here — it writes to stdout and corrupts the protocol.
  Always use sys.stderr or the logging module instead.
"""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from github_mcp import github_client

# Load GITHUB_TOKEN from a .env file if present.
# python-dotenv reads .env and sets the values into os.environ.
# This is the standard way to handle secrets in local dev.
load_dotenv()

# Set up logging to stderr (stdout is reserved for JSON-RPC).
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Create the MCP server instance
# FastMCP takes a server name — this is what shows up in Claude Desktop's UI.
# ---------------------------------------------------------------------------
mcp = FastMCP("GitHub Assistant")


# ===========================================================================
# TOOL #1 — search_repos
# ===========================================================================
@mcp.tool()
async def search_repos(
    query: str,
    sort: str = "stars",
    limit: int = 10,
) -> str:
    """
    Search GitHub repositories by keyword or topic.

    Use this when the user wants to discover repositories — e.g. "find Python
    HTTP libraries", "search for machine learning repos", or "what are popular
    React starter templates?".

    Args:
        query: GitHub search query. Supports qualifiers like:
               - "language:python" to filter by language
               - "stars:>1000" to filter by star count
               - "topic:machine-learning" to filter by topic
               Examples: "fastapi", "react hooks language:typescript stars:>500"
        sort:  Sort results by: "stars" (default), "forks", "updated", or "best-match"
        limit: Number of results to return (1-30, default 10)
    """
    log.info("Tool called: search_repos(query=%r, sort=%r, limit=%d)", query, sort, limit)

    # Clamp limit to a sensible range so we don't hammer the API
    limit = max(1, min(limit, 30))

    try:
        repos = await github_client.search_repos(query, sort=sort, per_page=limit)
    except Exception as e:
        return f"Error searching repositories: {e}"

    if not repos:
        return f"No repositories found for query: {query!r}"

    lines = [f"Found {len(repos)} repositories for '{query}':\n"]
    for i, r in enumerate(repos, 1):
        lines.append(
            f"{i}. **{r['full_name']}** ⭐ {r['stars']:,}\n"
            f"   {r['description']}\n"
            f"   Language: {r['language']} | Forks: {r['forks']:,} | "
            f"Open Issues: {r['open_issues']} | Updated: {r['updated_at']}\n"
            f"   {r['url']}\n"
        )
    return "\n".join(lines)


# ===========================================================================
# TOOL #2 — get_repo
# ===========================================================================
@mcp.tool()
async def get_repo(owner: str, repo: str) -> str:
    """
    Get detailed information about a specific GitHub repository.

    Use this when the user asks about a known repository — e.g. "tell me about
    the django/django repo", "how many stars does torvalds/linux have?", or
    "what language is facebook/react written in?".

    Args:
        owner: The repository owner — a GitHub username or organisation name.
               Examples: "microsoft", "torvalds", "psf"
        repo:  The repository name (not the full URL, just the name).
               Examples: "vscode", "linux", "cpython"
    """
    log.info("Tool called: get_repo(owner=%r, repo=%r)", owner, repo)

    try:
        r = await github_client.get_repo(owner, repo)
    except Exception as e:
        return f"Error fetching repository '{owner}/{repo}': {e}"

    topics_str = ", ".join(r["topics"]) if r["topics"] else "none"
    flags = []
    if r["is_fork"]:
        flags.append("Fork")
    if r["is_archived"]:
        flags.append("Archived")
    flags_str = " | ".join(flags) if flags else "Active"

    return (
        f"# {r['full_name']}\n\n"
        f"{r['description']}\n\n"
        f"**Stars:** {r['stars']:,}  |  **Forks:** {r['forks']:,}  |  "
        f"**Watchers:** {r['watchers']:,}\n"
        f"**Language:** {r['language']}\n"
        f"**Open Issues:** {r['open_issues']}\n"
        f"**License:** {r['license']}\n"
        f"**Default Branch:** {r['default_branch']}\n"
        f"**Topics:** {topics_str}\n"
        f"**Status:** {flags_str}\n"
        f"**Created:** {r['created_at']}  |  **Last Updated:** {r['updated_at']}\n"
        f"**URL:** {r['url']}"
    )


# ===========================================================================
# TOOL #3 — list_issues
# ===========================================================================
@mcp.tool()
async def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 20,
) -> str:
    """
    List issues for a GitHub repository.

    Use this when the user wants to see what bugs, feature requests, or tasks
    are open in a project — e.g. "what issues are open in pallets/flask?",
    "show me recently updated closed issues in django/django".

    Args:
        owner: Repository owner (GitHub username or organisation).
        repo:  Repository name.
        state: Filter by issue state: "open" (default), "closed", or "all".
        limit: Max number of issues to return (1-50, default 20).
    """
    log.info("Tool called: list_issues(owner=%r, repo=%r, state=%r)", owner, repo, state)

    limit = max(1, min(limit, 50))

    if state not in ("open", "closed", "all"):
        return "Invalid state. Use 'open', 'closed', or 'all'."

    try:
        issues = await github_client.list_issues(owner, repo, state=state, per_page=limit)
    except Exception as e:
        return f"Error listing issues for '{owner}/{repo}': {e}"

    if not issues:
        return f"No {state} issues found in {owner}/{repo}."

    lines = [f"**{state.capitalize()} issues in {owner}/{repo}** ({len(issues)} shown):\n"]
    for issue in issues:
        labels = f" [{', '.join(issue['labels'])}]" if issue["labels"] else ""
        lines.append(
            f"#{issue['number']} — {issue['title']}{labels}\n"
            f"  By @{issue['author']} | {issue['comments']} comment(s) | "
            f"Updated: {issue['updated_at']}\n"
            f"  {issue['url']}\n"
        )
    return "\n".join(lines)


# ===========================================================================
# TOOL #4 — get_issue
# ===========================================================================
@mcp.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> str:
    """
    Get the full details and description of a specific GitHub issue.

    Use this when the user wants to read the body/description of an issue —
    e.g. "what does issue #42 in pallets/flask say?", "show me the details of
    issue 1500 in django/django".

    Args:
        owner:        Repository owner (GitHub username or organisation).
        repo:         Repository name.
        issue_number: The issue number shown in the GitHub URL after /issues/
    """
    log.info("Tool called: get_issue(%r/%r#%d)", owner, repo, issue_number)

    try:
        i = await github_client.get_issue(owner, repo, issue_number)
    except Exception as e:
        return f"Error fetching issue #{issue_number} from '{owner}/{repo}': {e}"

    labels = ", ".join(i["labels"]) if i["labels"] else "none"
    assignees = ", ".join(f"@{a}" for a in i["assignees"]) if i["assignees"] else "unassigned"
    closed_line = f"**Closed:** {i['closed_at']}\n" if i["closed_at"] else ""

    return (
        f"# Issue #{i['number']}: {i['title']}\n\n"
        f"**State:** {i['state']}  |  **Author:** @{i['author']}\n"
        f"**Labels:** {labels}\n"
        f"**Assignees:** {assignees}\n"
        f"**Created:** {i['created_at']}  |  **Updated:** {i['updated_at']}\n"
        f"{closed_line}"
        f"**Comments:** {i['comments']}\n"
        f"**URL:** {i['url']}\n\n"
        f"---\n\n"
        f"{i['body']}"
    )


# ===========================================================================
# TOOL #5 — list_pull_requests
# ===========================================================================
@mcp.tool()
async def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 20,
) -> str:
    """
    List pull requests for a GitHub repository.

    Use this when the user wants to see what code changes are proposed or
    recently merged — e.g. "what PRs are open in fastapi/fastapi?",
    "show me recent merged PRs in torvalds/linux".

    Args:
        owner: Repository owner (GitHub username or organisation).
        repo:  Repository name.
        state: Filter by PR state: "open" (default), "closed", or "all".
        limit: Max number of PRs to return (1-50, default 20).
    """
    log.info("Tool called: list_pull_requests(owner=%r, repo=%r, state=%r)", owner, repo, state)

    limit = max(1, min(limit, 50))

    if state not in ("open", "closed", "all"):
        return "Invalid state. Use 'open', 'closed', or 'all'."

    try:
        prs = await github_client.list_pull_requests(owner, repo, state=state, per_page=limit)
    except Exception as e:
        return f"Error listing pull requests for '{owner}/{repo}': {e}"

    if not prs:
        return f"No {state} pull requests found in {owner}/{repo}."

    lines = [f"**{state.capitalize()} pull requests in {owner}/{repo}** ({len(prs)} shown):\n"]
    for pr in prs:
        draft_tag = " [DRAFT]" if pr["draft"] else ""
        lines.append(
            f"#{pr['number']}{draft_tag} — {pr['title']}\n"
            f"  By @{pr['author']} | {pr['head_branch']} → {pr['base_branch']} | "
            f"Updated: {pr['updated_at']}\n"
            f"  {pr['url']}\n"
        )
    return "\n".join(lines)


# ===========================================================================
# RESOURCE — repo readme
# ===========================================================================
@mcp.resource("repo://{owner}/{repo}/readme")
async def repo_readme(owner: str, repo: str) -> str:
    """
    The README file for a GitHub repository.

    This exposes the repository README as an MCP Resource — a readable piece
    of context that Claude can fetch and reason over.

    URI pattern: repo://{owner}/{repo}/readme
    Example:     repo://fastapi/fastapi/readme
    """
    log.info("Resource fetched: repo://%s/%s/readme", owner, repo)

    try:
        content = await github_client.get_readme(owner, repo)
        return content
    except Exception as e:
        return f"Could not fetch README for {owner}/{repo}: {e}"


# ===========================================================================
# Entry point
# ===========================================================================
def main() -> None:
    """
    Start the MCP server.

    mcp.run(transport="stdio") tells FastMCP to use stdin/stdout for
    communication. This is the standard transport for local MCP servers
    launched by Claude Desktop — it simply spawns this script as a subprocess
    and pipes JSON-RPC messages through stdin/stdout.
    """
    log.info("Starting GitHub Assistant MCP server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
