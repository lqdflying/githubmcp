"""GitHub Repo Reader MCP Server.

Provides MCP tools for reading GitHub repository contents, searching code,
viewing git history, and exploring repo structure — all via GitHub PAT auth.
"""

import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier

from src.github_client import GitHubClient, GitHubAPIError
from src.tools import file_ops, code_search, git_ops, repo_info

load_dotenv()

# ── Lifespan: create / validate / close the GitHub client ────────────

_github_client: GitHubClient | None = None


@asynccontextmanager
async def lifespan(server: FastMCP):
    global _github_client
    token = os.environ.get("GITHUB_PAT", "")
    if not token:
        print("ERROR: GITHUB_PAT environment variable is required.", file=sys.stderr)
        sys.exit(1)

    _github_client = GitHubClient(token)
    try:
        user = await _github_client.validate_token()
        print(f"Authenticated as GitHub user: {user.get('login', 'unknown')}", file=sys.stderr)
    except GitHubAPIError as e:
        print(f"ERROR: Failed to validate GitHub token: {e}", file=sys.stderr)
        await _github_client.close()
        sys.exit(1)

    yield

    await _github_client.close()


def _get_client() -> GitHubClient:
    if _github_client is None:
        raise RuntimeError("GitHub client not initialized. Server lifespan not started.")
    return _github_client


# ── Authentication ───────────────────────────────────────────────────

_mcp_api_token = os.environ.get("MCP_API_TOKEN", "")
if not _mcp_api_token:
    print("ERROR: MCP_API_TOKEN environment variable is required.", file=sys.stderr)
    sys.exit(1)

_auth = DebugTokenVerifier(
    validate=lambda token: token == _mcp_api_token,
    client_id="mcp-client",
    scopes=["read"],
)

# ── Initialize FastMCP server ────────────────────────────────────────

mcp = FastMCP(
    "GitHub Repo Reader",
    instructions=(
        "Read and explore GitHub repositories: browse files, search code, "
        "view git history, diffs, blame, and repository structure. "
        "Authenticate with a GitHub Personal Access Token."
    ),
    lifespan=lifespan,
    auth=_auth,
)


# ═══════════════════════════════════════════════════════════════════════
# FILE OPERATION TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def read_file(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read file contents from a GitHub repository, optionally returning a specific line range.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository (e.g. "src/main.py").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        start_line: First line to return (1-based, inclusive). Omit to start from beginning.
        end_line: Last line to return (1-based, inclusive). Omit to read to end.
    """
    return await file_ops.read_file(_get_client(), owner, repo, path, ref, start_line, end_line)


@mcp.tool()
async def list_directory(
    owner: str,
    repo: str,
    path: str = "",
    ref: str | None = None,
) -> str:
    """List contents of a directory in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: Directory path within the repository. Use "" for root.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
    """
    return await file_ops.list_directory(_get_client(), owner, repo, path, ref)


@mcp.tool()
async def find_files(
    owner: str,
    repo: str,
    pattern: str,
    ref: str | None = None,
) -> str:
    """Search for files matching a glob pattern in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        pattern: Glob pattern to match file paths (e.g. "**/*.py", "src/**/*.ts", "*.md").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
    """
    return await file_ops.find_files(_get_client(), owner, repo, pattern, ref)


# ═══════════════════════════════════════════════════════════════════════
# CODE SEARCH TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def search_code(
    owner: str,
    repo: str,
    query: str,
    is_regexp: bool = False,
    include_pattern: str | None = None,
    ref: str | None = None,
    max_results: int = 50,
) -> str:
    """Search for text or regex patterns across files in a GitHub repository.

    For simple text queries on the default branch, uses GitHub's Search API.
    For regex patterns or specific branches, fetches files and searches locally.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        query: Search string or regex pattern.
        is_regexp: If True, treat query as a Python regex pattern.
        include_pattern: Optional glob pattern to limit search to matching files (e.g. "*.py").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        max_results: Maximum number of matching lines to return (default: 50).
    """
    return await code_search.search_code(
        _get_client(), owner, repo, query, is_regexp, include_pattern, ref, max_results
    )


@mcp.tool()
async def get_file_summary(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    preview_lines: int = 20,
) -> str:
    """Get an overview of a file including size, line count, language, and a content preview.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        preview_lines: Number of lines to show as preview (default: 20).
    """
    return await code_search.get_file_summary(_get_client(), owner, repo, path, ref, preview_lines)


# ═══════════════════════════════════════════════════════════════════════
# GIT OPERATION TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_branches(
    owner: str,
    repo: str,
) -> str:
    """List all branches in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await git_ops.list_branches(_get_client(), owner, repo)


@mcp.tool()
async def get_commits(
    owner: str,
    repo: str,
    ref: str | None = None,
    path: str | None = None,
    limit: int = 20,
) -> str:
    """Get commit history for a repository or specific file.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        ref: Branch, tag, or commit SHA to start from. Defaults to the repo's default branch.
        path: Optional file path to filter commits that touched this file.
        limit: Maximum number of commits to return (default: 20).
    """
    return await git_ops.get_commits(_get_client(), owner, repo, ref, path, limit)


@mcp.tool()
async def get_diff(
    owner: str,
    repo: str,
    base: str,
    head: str,
) -> str:
    """Compare two branches, tags, or commits and show the diff.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        base: Base ref (branch, tag, or commit SHA) for comparison.
        head: Head ref (branch, tag, or commit SHA) for comparison.
    """
    return await git_ops.get_diff(_get_client(), owner, repo, base, head)


@mcp.tool()
async def get_blame(
    owner: str,
    repo: str,
    path: str,
    ref: str = "HEAD",
) -> str:
    """Get blame information for a file, showing which commit last modified each line.

    Uses the GitHub GraphQL API to retrieve blame data.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to HEAD.
    """
    return await git_ops.get_blame(_get_client(), owner, repo, path, ref)


@mcp.tool()
async def get_file_history(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    limit: int = 20,
) -> str:
    """Get the commit history for a specific file.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        limit: Maximum number of commits to return (default: 20).
    """
    return await git_ops.get_file_history(_get_client(), owner, repo, path, ref, limit)


# ═══════════════════════════════════════════════════════════════════════
# REPOSITORY INFO TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_repo_info(
    owner: str,
    repo: str,
) -> str:
    """Get metadata and overview information about a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await repo_info.get_repo_info(_get_client(), owner, repo)


@mcp.tool()
async def get_repo_structure(
    owner: str,
    repo: str,
    ref: str | None = None,
    max_depth: int | None = None,
    path_filter: str | None = None,
) -> str:
    """Get the file/folder tree structure of a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        max_depth: Maximum depth of tree to display (e.g. 2 for top-level + one level).
        path_filter: Optional glob pattern to filter paths (e.g. "src/**").
    """
    return await repo_info.get_repo_structure(_get_client(), owner, repo, ref, max_depth, path_filter)


@mcp.tool()
async def get_languages(
    owner: str,
    repo: str,
) -> str:
    """Get the programming language breakdown of a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await repo_info.get_languages(_get_client(), owner, repo)


# ═══════════════════════════════════════════════════════════════════════
# UTILITY TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_rate_limit() -> str:
    """Check the current GitHub API rate limit status.

    Returns:
        Current rate limit remaining, total, and reset time.
    """
    client = _get_client()
    if client.rate_limit:
        import datetime

        reset_dt = datetime.datetime.fromtimestamp(
            client.rate_limit.reset_at, tz=datetime.timezone.utc
        )
        return (
            f"Rate limit: {client.rate_limit.remaining}/{client.rate_limit.limit} remaining\n"
            f"Resets at: {reset_dt.isoformat()}"
        )
    return "Rate limit info not yet available (no API calls made)."


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
    )
