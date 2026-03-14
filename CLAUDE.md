# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run the server
python server.py

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_file_ops.py

# Run a single test
pytest tests/test_file_ops.py::test_read_file_success

# Lint and format
ruff check .
ruff format .
```

## Environment

Two environment variables are **required** at startup — the server exits immediately if either is missing:

- `GITHUB_PAT` — GitHub Personal Access Token (classic: `repo` scope; fine-grained: `Contents: Read` + `Metadata: Read`)
- `MCP_API_TOKEN` — Bearer token clients must send to authenticate against the MCP endpoint

Optional: `HOST` (default `0.0.0.0`), `PORT` (default `8000`).

Copy `.env.example` to `.env` and fill in both values before running.

## Architecture

```
server.py                    ← FastMCP entry point; all 14 MCP tool definitions live here
src/
├── github_client.py         ← Async REST + GraphQL client (httpx); the only place that calls GitHub API
├── cache.py                 ← Two shared TTLCache instances: tree_cache (5 min), file_cache (2 min)
└── tools/
    ├── file_ops.py          ← read_file, list_directory, find_files
    ├── code_search.py       ← search_code, get_file_summary
    ├── git_ops.py           ← list_branches, get_commits, get_diff, get_blame, get_file_history
    └── repo_info.py         ← get_repo_info, get_repo_structure, get_languages, get_rate_limit
tests/
├── conftest.py              ← Shared mock_client fixture (AsyncMock of GitHubClient)
└── test_*.py                ← Unit tests per tool module
```

### Two-layer tool pattern

`server.py` contains thin `@mcp.tool()` wrappers that validate nothing — they just call `_get_client()` and delegate to a pure async function in `src/tools/`. All real logic lives in the tool modules. This keeps tools independently testable without FastMCP.

### GitHubClient

A single `GitHubClient` instance is created at startup (lifespan) and accessed via `_get_client()`. It wraps:
- REST calls via `self._http` (httpx.AsyncClient with `api.github.com` base URL)
- GraphQL calls via `self._graphql_http` (used only for blame)
- Rate limit tracking — updated from response headers on every call

Files > 1 MB are fetched via the Git Blobs API (`get_blob`) instead of the Contents API. The `get_full_tree` helper resolves branch/tag names through the refs API before fetching the recursive tree.

### Caching

`tree_cache` and `file_cache` in `src/cache.py` are module-level singletons shared across all tool calls. Cache keys use the pattern `"tree:{owner}/{repo}:{ref}"`. The TTLCache is not thread-safe but that is acceptable for the async single-process server model.

### Search strategy

`search_code` uses two paths: simple text queries on the default branch go to GitHub's Search API (subject to 30 req/min rate limit); regex patterns or branch-specific searches fetch files locally and search with Python `re`.

### Auth

MCP endpoint auth uses FastMCP's `DebugTokenVerifier` with a simple equality check against `MCP_API_TOKEN`. The `/health` endpoint is unauthenticated.
