"""
GitHub API client.

This module is a thin wrapper around the GitHub REST API v3.
All methods are async (non-blocking) — they use httpx.AsyncClient so
multiple requests can be in-flight concurrently without blocking.

Why a separate client module?
  - Keeps the MCP tool definitions clean (they just call these methods)
  - Easy to unit-test without the MCP layer
  - If GitHub ever changes their API, you only update this file
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"


def _get_headers() -> dict[str, str]:
    """
    Build the HTTP headers for every GitHub API request.

    The 'Authorization' header is only added when a GITHUB_TOKEN environment
    variable is present. Without a token, GitHub allows ~60 requests/hour.
    With a token: 5,000 requests/hour — more than enough for any real use.

    The 'X-GitHub-Api-Version' header pins us to a specific API version so
    GitHub won't break our code when they release new versions.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    """
    Make a single authenticated GET request to the GitHub API.

    Returns the parsed JSON body on success.
    Raises httpx.HTTPStatusError on 4xx/5xx responses — callers handle this.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, headers=_get_headers(), params=params, timeout=15.0)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Tool #1 helper: Search repositories
# ---------------------------------------------------------------------------

async def search_repos(query: str, sort: str = "stars", per_page: int = 10) -> list[dict]:
    """
    Search GitHub repositories using the Search API.

    GitHub's search API returns a 'items' list — each item is a repository object.
    We return only the fields we care about to keep responses concise.

    Args:
        query:    GitHub search query string (e.g. "fastapi language:python")
        sort:     Sort by "stars", "forks", "updated", or "best-match"
        per_page: How many results to return (max 100)
    """
    data = await _get(
        f"{GITHUB_API_BASE}/search/repositories",
        params={"q": query, "sort": sort, "per_page": per_page},
    )
    repos = []
    for item in data.get("items", []):
        repos.append({
            "full_name": item["full_name"],
            "description": item.get("description") or "No description",
            "stars": item["stargazers_count"],
            "forks": item["forks_count"],
            "language": item.get("language") or "Unknown",
            "open_issues": item["open_issues_count"],
            "url": item["html_url"],
            "updated_at": item["updated_at"][:10],  # just the date part
        })
    return repos


# ---------------------------------------------------------------------------
# Tool #2 helper: Get a single repository
# ---------------------------------------------------------------------------

async def get_repo(owner: str, repo: str) -> dict:
    """
    Fetch metadata for a specific repository.

    Args:
        owner: Repository owner (user or organisation name)
        repo:  Repository name
    """
    data = await _get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}")
    return {
        "full_name": data["full_name"],
        "description": data.get("description") or "No description",
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "watchers": data["watchers_count"],
        "language": data.get("language") or "Unknown",
        "open_issues": data["open_issues_count"],
        "default_branch": data["default_branch"],
        "license": data.get("license", {}).get("name") if data.get("license") else "No license",
        "topics": data.get("topics", []),
        "created_at": data["created_at"][:10],
        "updated_at": data["updated_at"][:10],
        "url": data["html_url"],
        "is_fork": data["fork"],
        "is_archived": data["archived"],
    }


# ---------------------------------------------------------------------------
# Tool #3 helper: List issues
# ---------------------------------------------------------------------------

async def list_issues(owner: str, repo: str, state: str = "open", per_page: int = 20) -> list[dict]:
    """
    List issues for a repository.

    GitHub's /repos/{owner}/{repo}/issues endpoint returns both issues and
    pull requests. We filter out PRs by checking for the 'pull_request' key,
    which is only present on PR objects.

    Note: Some repos (e.g. django/django) disable GitHub Issues and use an
    external tracker — this will return an empty list for those.

    Args:
        owner:    Repository owner
        repo:     Repository name
        state:    "open", "closed", or "all" (default: "open")
        per_page: Max number of issues to return
    """
    data = await _get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
        params={"state": state, "per_page": per_page, "sort": "updated"},
    )
    issues = []
    for item in data:
        # Skip pull requests — they appear in the issues endpoint too
        if "pull_request" in item:
            continue
        issues.append({
            "number": item["number"],
            "title": item["title"],
            "state": item["state"],
            "author": item["user"]["login"],
            "labels": [label["name"] for label in item.get("labels", [])],
            "comments": item["comments"],
            "created_at": item["created_at"][:10],
            "updated_at": item["updated_at"][:10],
            "url": item["html_url"],
        })
    return issues


# ---------------------------------------------------------------------------
# Tool #4 helper: Get a single issue
# ---------------------------------------------------------------------------

async def get_issue(owner: str, repo: str, issue_number: int) -> dict:
    """
    Fetch the full detail of a single issue, including body text.

    Args:
        owner:        Repository owner
        repo:         Repository name
        issue_number: The issue number (the # in the GitHub URL)
    """
    data = await _get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}")
    return {
        "number": data["number"],
        "title": data["title"],
        "state": data["state"],
        "author": data["user"]["login"],
        "body": data.get("body") or "No description provided.",
        "labels": [label["name"] for label in data.get("labels", [])],
        "assignees": [a["login"] for a in data.get("assignees", [])],
        "comments": data["comments"],
        "created_at": data["created_at"][:10],
        "updated_at": data["updated_at"][:10],
        "closed_at": data["closed_at"][:10] if data.get("closed_at") else None,
        "url": data["html_url"],
    }


# ---------------------------------------------------------------------------
# Tool #5 helper: List pull requests
# ---------------------------------------------------------------------------

async def list_pull_requests(owner: str, repo: str, state: str = "open", per_page: int = 20) -> list[dict]:
    """
    List pull requests for a repository.

    Args:
        owner:    Repository owner
        repo:     Repository name
        state:    "open", "closed", or "all"
        per_page: Max number of PRs to return
    """
    data = await _get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
        params={"state": state, "per_page": per_page, "sort": "updated"},
    )
    prs = []
    for item in data:
        prs.append({
            "number": item["number"],
            "title": item["title"],
            "state": item["state"],
            "author": item["user"]["login"],
            "draft": item.get("draft", False),
            "head_branch": item["head"]["ref"],
            "base_branch": item["base"]["ref"],
            "commits": item.get("commits"),  # may be None in list view
            "changed_files": item.get("changed_files"),  # may be None in list view
            "created_at": item["created_at"][:10],
            "updated_at": item["updated_at"][:10],
            "url": item["html_url"],
        })
    return prs


# ---------------------------------------------------------------------------
# Resource helper: Get README
# ---------------------------------------------------------------------------

async def get_readme(owner: str, repo: str) -> str:
    """
    Fetch the README for a repository.

    GitHub returns the README content as base64-encoded text.
    We decode it and return the raw markdown string.

    Args:
        owner: Repository owner
        repo:  Repository name
    """
    data = await _get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme")
    # Content is base64-encoded with newlines — strip them before decoding
    content_b64 = data["content"].replace("\n", "")
    return base64.b64decode(content_b64).decode("utf-8", errors="replace")
