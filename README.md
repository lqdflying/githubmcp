[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/lqdflying-githubmcp-badge.png)](https://mseep.ai/app/lqdflying-githubmcp)

# GitHub Repo Reader & Code Tools MCP Server

An MCP (Model Context Protocol) server built with **FastMCP** that lets AI agents read, search, inspect, and write GitHub repositories through the GitHub API.

GitHub API access can use either:

- A server-level `GITHUB_PAT`
- A per-request GitHub PAT supplied by the MCP client with `X-GitHub-PAT`

MCP server authentication remains separate and can use a static bearer token, GitHub OAuth, or both.

## Documentation

The long-form setup and reference docs have moved to the GitHub Wiki:

- [Full Documentation](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation)
- [Setup Scenarios](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#setup-scenarios)
- [Authentication and Access](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#how-authentication-works)
- [Per-User GitHub PATs](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#per-user-github-pats)
- [VS Code Integration](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#vs-code-integration)
- [Copilot Studio Integration](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#copilot-studio-integration)
- [Tool Reference](https://github.com/lqdflying/githubmcp/wiki/Full-Documentation#tool-reference--examples)

## Features

Read and exploration tools:

- Read files and directories
- Search code with text or regex
- List branches and commits
- Compare refs and inspect diffs
- Show blame and file history
- Inspect repository metadata, languages, and structure

Write and automation tools:

- Create branches
- Push one or more files as a commit
- Delete files
- Create and manage pull requests
- Create issues and PR comments
- List, inspect, and trigger GitHub Actions workflows

Task tools:

- `todo_write`
- `todo_update`
- `todo_read`

## Quick Start

```bash
git clone <this-repo-url>
cd githubmcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

For single-user/server-token mode, configure:

```env
GITHUB_TOKEN_MODE=env
GITHUB_PAT=ghp_your_github_pat_here
MCP_AUTH_MODE=token
MCP_API_TOKEN=your_secret_mcp_token_here
```

Start the server:

```bash
python server.py
```

## Per-User Private Repo Access

For a shared MCP server where each user should access private repos through their own GitHub PAT, configure:

```env
GITHUB_TOKEN_MODE=request
GITHUB_PAT_HEADER=X-GitHub-PAT
GITHUB_CLIENT_CACHE_MAX_SIZE=128
GITHUB_CLIENT_CACHE_TTL_SECONDS=1800
GITHUB_VALIDATE_REQUEST_PAT=true
```

Then MCP clients send MCP authentication and GitHub access separately:

```json
{
  "headers": {
    "Authorization": "Bearer your_mcp_api_token",
    "X-GitHub-PAT": "github_pat_user_specific_token"
  }
}
```

`Authorization` is reserved for MCP server authentication. Do not use it for the GitHub PAT header.

Request-scoped GitHub clients are cached with LRU/TTL eviction and closed when evicted. New request PATs are validated before caching by default.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

See the [wiki](https://github.com/lqdflying/githubmcp/wiki) for full setup, deployment, OAuth, client integration, architecture, and tool reference documentation.
