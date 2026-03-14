# GitHub Assistant MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects Claude Desktop to the GitHub API. Ask Claude natural-language questions about any public GitHub repository — issues, pull requests, repo metadata, READMEs — without leaving your conversation.

## What is MCP?

MCP (Model Context Protocol) is an open standard that lets AI applications connect to external tools and data sources through a uniform interface. Think of it as a USB-C port for AI — any MCP-compatible client (Claude Desktop, Cursor, VS Code Copilot, etc.) can plug into any MCP server.

```
Claude Desktop (MCP Host)
       |
       |  stdio — JSON-RPC 2.0
       v
GitHub Assistant MCP Server   <-- this project
       |
       |  HTTPS
       v
  GitHub REST API v3
```

When you ask Claude *"what are the open issues in microsoft/vscode?"*, Claude calls this server's `list_issues` tool, the server fetches data from GitHub, and returns the answer — all transparently within the conversation.

## Tools

| Tool | Description |
|------|-------------|
| `search_repos` | Search GitHub repos by keyword. Supports qualifiers like `language:python`, `stars:>1000` |
| `get_repo` | Get metadata for a specific repo: stars, forks, language, license, topics |
| `list_issues` | List open/closed issues for a repo (excludes PRs) |
| `get_issue` | Get the full body and details of a specific issue by number |
| `list_pull_requests` | List open/closed PRs including draft status and branch info |

## Resources

| URI Pattern | Description |
|-------------|-------------|
| `repo://{owner}/{repo}/readme` | The raw README markdown for any repository |

## Example Conversations

> "Search for the most starred Python web frameworks on GitHub"

> "Tell me about the microsoft/vscode repository"

> "What are the 10 most recently updated open issues in microsoft/vscode?"

> "Show me the details of issue #301645 in microsoft/vscode"

> "What open pull requests are there in fastapi/fastapi?"

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude Desktop](https://claude.ai/download)
- A [GitHub Personal Access Token](https://github.com/settings/tokens) (for 5,000 req/hr vs 60 without)

### Install

```bash
git clone https://github.com/yourusername/github-mcp
cd github-mcp

# Install dependencies
uv sync

# Copy and fill in your token
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=ghp_your_token_here
```

### Connect to Claude Desktop

Add the following to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "github-assistant": {
      "command": "/path/to/uv",
      "args": [
        "--directory", "/absolute/path/to/github-mcp",
        "run", "python", "-m", "github_mcp.server"
      ],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

Restart Claude Desktop. You should see a hammer icon in the chat input — that's your MCP tools.

## Project Structure

```
github-mcp/
├── src/
│   └── github_mcp/
│       ├── __init__.py
│       ├── github_client.py   # GitHub REST API wrapper (pure async httpx)
│       └── server.py          # MCP server — tool & resource definitions
├── .env                       # Your GITHUB_TOKEN (never commit this)
├── .gitignore
├── pyproject.toml
└── README.md
```

### Architecture

**`github_client.py`** is a thin async wrapper around the GitHub REST API v3. It has no knowledge of MCP — just Python functions that return dicts. This separation makes it easy to test independently.

**`server.py`** is the MCP layer. It creates a `FastMCP` instance and decorates functions with `@mcp.tool()` and `@mcp.resource()`. FastMCP auto-generates the JSON Schema for each tool from Python type hints and docstrings — the same docstring you write for humans is what Claude reads to decide *when* to call your tool.

**Transport:** stdio (stdin/stdout). Claude Desktop launches this server as a subprocess and sends JSON-RPC 2.0 messages through stdin. The server writes responses to stdout. This is why we log to stderr — stdout is reserved for the protocol.

## Key Concepts Learned

- **MCP primitives**: Tools (callable functions), Resources (readable data), Prompts (templates)
- **JSON-RPC 2.0**: The wire protocol — request/response with `id`, notification without
- **Tool descriptions matter**: The LLM reads your docstring to decide when to call a tool
- **stdio transport**: No HTTP server needed for local tools — just a process with pipes
- **Async Python**: `httpx.AsyncClient` for non-blocking GitHub API calls
- **Auth patterns**: Token injection via environment variables — never hardcoded

## License

MIT
