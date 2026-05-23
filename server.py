"""GitHub Repo Reader MCP Server.

Provides MCP tools for reading GitHub repository contents, searching code,
viewing git history, and exploring repo structure — all via GitHub PAT auth.
"""

import logging
import os
import sys
import time
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware
from fastmcp.server.transforms import Visibility
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.auth import setup_auth, parse_bool
from src.github_client import GitHubClient, GitHubAPIError
from src.tools import file_ops, code_search, git_ops, repo_info, write_ops, pr_ops, todo_ops

load_dotenv()

# ── Read-only mode ────────────────────────────────────────────────────
# When MCP_READ_ONLY=true, all write/PR/CI tools are skipped at registration
# time. Use this when your GitHub PATs only have read permissions.
# load_dotenv() must be called first so .env values are available here.
_READ_ONLY = parse_bool(os.environ.get("MCP_READ_ONLY", "false"), default=False)
_VALID_GITHUB_TOKEN_MODES = {"env", "request", "request_or_env"}
_GITHUB_TOKEN_MODE = os.environ.get("GITHUB_TOKEN_MODE", "env").strip().lower()
_GITHUB_PAT_HEADER = os.environ.get("GITHUB_PAT_HEADER", "X-GitHub-PAT").strip() or "X-GitHub-PAT"
_GITHUB_CLIENT_CACHE_MAX_SIZE_DEFAULT = 128
_GITHUB_CLIENT_CACHE_TTL_SECONDS_DEFAULT = 1800
_VALIDATE_REQUEST_PAT = parse_bool(
    os.environ.get("GITHUB_VALIDATE_REQUEST_PAT", "true"),
    default=True,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mcp")
logger = logging.getLogger(__name__)

# ── Lifespan: create / validate / close the GitHub client ────────────

_github_client: GitHubClient | None = None


@dataclass
class _CachedGitHubClient:
    client: GitHubClient
    created_at: float
    last_used_at: float


_request_github_clients: OrderedDict[str, _CachedGitHubClient] = OrderedDict()
_request_github_clients_lock = asyncio.Lock()


def _get_github_token_mode() -> str:
    if _GITHUB_TOKEN_MODE not in _VALID_GITHUB_TOKEN_MODES:
        print(
            "ERROR: GITHUB_TOKEN_MODE must be one of: env, request, request_or_env.",
            file=sys.stderr,
        )
        sys.exit(1)
    if (
        _GITHUB_TOKEN_MODE in {"request", "request_or_env"}
        and _GITHUB_PAT_HEADER.lower() == "authorization"
    ):
        print(
            "ERROR: GITHUB_PAT_HEADER must not be Authorization. "
            "Authorization is reserved for MCP server authentication.",
            file=sys.stderr,
        )
        sys.exit(1)
    return _GITHUB_TOKEN_MODE


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        print(f"ERROR: {name} must be a positive integer.", file=sys.stderr)
        sys.exit(1)
    if value < 1:
        print(f"ERROR: {name} must be a positive integer.", file=sys.stderr)
        sys.exit(1)
    return value


def _request_client_cache_max_size() -> int:
    return _positive_int_env(
        "GITHUB_CLIENT_CACHE_MAX_SIZE",
        _GITHUB_CLIENT_CACHE_MAX_SIZE_DEFAULT,
    )


def _request_client_cache_ttl_seconds() -> int:
    return _positive_int_env(
        "GITHUB_CLIENT_CACHE_TTL_SECONDS",
        _GITHUB_CLIENT_CACHE_TTL_SECONDS_DEFAULT,
    )


def _normalize_pat(raw: str | None) -> str | None:
    if raw is None:
        return None
    token = raw.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def _request_pat() -> str | None:
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return _normalize_pat(request.headers.get(_GITHUB_PAT_HEADER))


def _token_cache_key(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


async def _close_client(client: GitHubClient) -> None:
    try:
        await client.close()
    except Exception as e:
        log.warning("Failed to close GitHub client: %s", e)


async def _close_clients(clients: list[GitHubClient]) -> None:
    for client in clients:
        await _close_client(client)


def _collect_expired_request_clients(now: float) -> list[GitHubClient]:
    ttl_seconds = _request_client_cache_ttl_seconds()
    expired_keys = [
        key
        for key, entry in _request_github_clients.items()
        if now - entry.last_used_at >= ttl_seconds
    ]
    return [_request_github_clients.pop(key).client for key in expired_keys]


def _collect_overflow_request_clients() -> list[GitHubClient]:
    max_size = _request_client_cache_max_size()
    evicted: list[GitHubClient] = []
    while len(_request_github_clients) > max_size:
        _, entry = _request_github_clients.popitem(last=False)
        evicted.append(entry.client)
    return evicted


async def _prune_request_client_cache(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    await _close_clients(_collect_expired_request_clients(now))
    await _close_clients(_collect_overflow_request_clients())


async def _client_for_token(token: str) -> GitHubClient:
    key = _token_cache_key(token)
    now = time.monotonic()

    async with _request_github_clients_lock:
        await _prune_request_client_cache(now)

        entry = _request_github_clients.get(key)
        if entry is not None:
            entry.last_used_at = now
            _request_github_clients.move_to_end(key)
            return entry.client

    client = GitHubClient(token)
    if _VALIDATE_REQUEST_PAT:
        try:
            await client.validate_token()
        except GitHubAPIError as e:
            await _close_client(client)
            raise ToolError(
                f"GitHub PAT from {_GITHUB_PAT_HEADER} is invalid or unauthorized: {e}"
            ) from e

    now = time.monotonic()
    async with _request_github_clients_lock:
        await _prune_request_client_cache(now)
        entry = _request_github_clients.get(key)
        if entry is not None:
            entry.last_used_at = now
            _request_github_clients.move_to_end(key)
            await _close_client(client)
            return entry.client

        _request_github_clients[key] = _CachedGitHubClient(
            client=client,
            created_at=now,
            last_used_at=now,
        )
        _request_github_clients.move_to_end(key)
        await _close_clients(_collect_overflow_request_clients())
        return client


async def _close_github_clients() -> None:
    global _github_client
    if _github_client is not None:
        await _close_client(_github_client)
        _github_client = None

    async with _request_github_clients_lock:
        clients = [entry.client for entry in _request_github_clients.values()]
        _request_github_clients.clear()
        await _close_clients(clients)


@asynccontextmanager
async def lifespan(server: FastMCP):
    global _github_client
    github_token_mode = _get_github_token_mode()
    if github_token_mode in {"request", "request_or_env"}:
        _request_client_cache_max_size()
        _request_client_cache_ttl_seconds()
    token = os.environ.get("GITHUB_PAT", "").strip()
    needs_env_token = github_token_mode == "env"
    can_use_env_token = github_token_mode in {"env", "request_or_env"}

    if needs_env_token and not token:
        print("ERROR: GITHUB_PAT environment variable is required.", file=sys.stderr)
        sys.exit(1)

    if can_use_env_token and token:
        _github_client = GitHubClient(token)
        try:
            user = await _github_client.validate_token()
            print(f"Authenticated as GitHub user: {user.get('login', 'unknown')}", file=sys.stderr)
        except GitHubAPIError as e:
            print(f"ERROR: Failed to validate GitHub token: {e}", file=sys.stderr)
            await _close_github_clients()
            sys.exit(1)
    elif github_token_mode == "request":
        print(
            f"GitHub PAT source: per-request header ({_GITHUB_PAT_HEADER}); "
            "GITHUB_PAT is not required.",
            file=sys.stderr,
        )
    else:
        print(
            f"GitHub PAT source: per-request header ({_GITHUB_PAT_HEADER}); "
            "no GITHUB_PAT fallback configured.",
            file=sys.stderr,
        )

    if _READ_ONLY:
        print(
            "Running in READ-ONLY mode (MCP_READ_ONLY=true): write/CI/todo tools are disabled. "
            "Read-only PR tools (list, get) remain available.",
            file=sys.stderr,
        )
    else:
        print(
            "Running in READ+WRITE mode. "
            "Ensure configured GitHub PATs have write permissions (classic: 'repo'; "
            "fine-grained: Contents+PR+Actions write). "
            "Set MCP_READ_ONLY=true to disable write tools.",
            file=sys.stderr,
        )

    try:
        yield
    finally:
        await _close_github_clients()


async def _get_client() -> GitHubClient:
    github_token_mode = _get_github_token_mode()

    if github_token_mode in {"request", "request_or_env"}:
        token = _request_pat()
        if token:
            return await _client_for_token(token)
        if github_token_mode == "request":
            raise ToolError(
                f"Missing GitHub PAT header: {_GITHUB_PAT_HEADER}. "
                "Send the GitHub token separately from MCP authentication."
            )

    if _github_client is None:
        raise ToolError(
            "No GitHub PAT is available. Set GITHUB_PAT or send "
            f"{_GITHUB_PAT_HEADER} with the request."
        )
    return _github_client


async def _safe(coro):
    """Await a tool coroutine, translating known domain errors to ToolError.

    When mask_error_details=True, FastMCP converts unhandled exceptions into
    opaque "Error calling tool" messages.  This helper translates expected
    GitHubAPIError (404, 401, 403, etc.) into ToolError so the client sees
    the actionable message while unexpected errors remain masked.
    """
    try:
        return await coro
    except GitHubAPIError as e:
        raise ToolError(str(e)) from e


# ── Authentication ───────────────────────────────────────────────────
# All auth logic lives in src/auth/. setup_auth() reads env vars, validates
# them, and returns the appropriate FastMCP auth provider.

_auth = setup_auth()

# ── Initialize FastMCP server ────────────────────────────────────────

mcp = FastMCP(
    "GitHub Repo Reader & Code Tools",
    instructions=(
        "Read and explore GitHub repositories: browse files, search code, "
        "view git history, diffs, blame, and repository structure. "
        "Write code: create branches, commit files, open pull requests, "
        "manage issues, and trigger CI workflows. "
        "Authenticate with a GitHub Personal Access Token."
    ),
    lifespan=lifespan,
    auth=_auth,
    mask_error_details=True,
)

# When MCP_READ_ONLY=true, hide all tools tagged "write" via Visibility transform.
# This covers: file writes, CI triggers, PR mutations, and todo writes.
# Read-only PR tools (list_pull_requests, get_pull_request) keep the "read" tag
# and are NOT hidden, so they remain available even in read-only mode.
if _READ_ONLY:
    mcp.add_transform(Visibility(False, tags={"write"}))


# ── Logging middleware ───────────────────────────────────────────────


class LoggingMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        name = context.message.name
        args = context.message.arguments or {}
        owner = args.get("owner", "")
        repo = args.get("repo", "")
        extra = {k: v for k, v in args.items() if k not in ("owner", "repo") and v is not None}
        target = f"{owner}/{repo}" if owner else ""
        extra_str = f"  {extra}" if extra else ""
        log.info(f"▶ {name}  {target}{extra_str}")
        t0 = time.monotonic()
        try:
            result = await call_next(context)
            elapsed = (time.monotonic() - t0) * 1000
            # Estimate response size from result content
            size = ""
            try:
                content = result.content
                if content:
                    chars = sum(len(c.text) for c in content if hasattr(c, "text"))
                    size = f"  {chars:,} chars"
            except Exception:
                pass
            log.info(f"✓ {name}  {elapsed:.0f}ms{size}")
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            log.error(f"✗ {name}  FAILED ({elapsed:.0f}ms): {e}  args={args}")
            raise


mcp.add_middleware(LoggingMiddleware())


# ── Health check endpoint ────────────────────────────────────────────


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "GitHub Repo Reader"})


# ═══════════════════════════════════════════════════════════════════════
# FILE OPERATION TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"read", "file"}, annotations={"readOnlyHint": True})
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
    return await _safe(file_ops.read_file(await _get_client(), owner, repo, path, ref, start_line, end_line))


@mcp.tool(tags={"read", "file"}, annotations={"readOnlyHint": True})
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
    return await _safe(file_ops.list_directory(await _get_client(), owner, repo, path, ref))


@mcp.tool(tags={"read", "file"}, annotations={"readOnlyHint": True})
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
    return await _safe(file_ops.find_files(await _get_client(), owner, repo, pattern, ref))


# ═══════════════════════════════════════════════════════════════════════
# CODE SEARCH TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"read", "search"}, annotations={"readOnlyHint": True}, timeout=30)
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
    return await _safe(code_search.search_code(
        await _get_client(), owner, repo, query, is_regexp, include_pattern, ref, max_results
    ))


@mcp.tool(tags={"read", "search"}, annotations={"readOnlyHint": True})
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
    return await _safe(code_search.get_file_summary(await _get_client(), owner, repo, path, ref, preview_lines))


# ═══════════════════════════════════════════════════════════════════════
# GIT OPERATION TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"read", "git"}, annotations={"readOnlyHint": True})
async def list_branches(
    owner: str,
    repo: str,
) -> str:
    """List all branches in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await _safe(git_ops.list_branches(await _get_client(), owner, repo))


@mcp.tool(tags={"read", "git"}, annotations={"readOnlyHint": True})
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
    return await _safe(git_ops.get_commits(await _get_client(), owner, repo, ref, path, limit))


@mcp.tool(tags={"read", "git"}, annotations={"readOnlyHint": True}, timeout=30)
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
    return await _safe(git_ops.get_diff(await _get_client(), owner, repo, base, head))


@mcp.tool(tags={"read", "git"}, annotations={"readOnlyHint": True}, timeout=30)
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
    return await _safe(git_ops.get_blame(await _get_client(), owner, repo, path, ref))


@mcp.tool(tags={"read", "git"}, annotations={"readOnlyHint": True})
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
    return await _safe(git_ops.get_file_history(await _get_client(), owner, repo, path, ref, limit))


# ═══════════════════════════════════════════════════════════════════════
# REPOSITORY INFO TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"read", "repo"}, annotations={"readOnlyHint": True})
async def get_repo_info(
    owner: str,
    repo: str,
) -> str:
    """Get metadata and overview information about a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await _safe(repo_info.get_repo_info(await _get_client(), owner, repo))


@mcp.tool(tags={"read", "repo"}, annotations={"readOnlyHint": True})
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
    return await _safe(repo_info.get_repo_structure(
        await _get_client(), owner, repo, ref, max_depth, path_filter
    ))


@mcp.tool(tags={"read", "repo"}, annotations={"readOnlyHint": True})
async def get_languages(
    owner: str,
    repo: str,
) -> str:
    """Get the programming language breakdown of a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
    """
    return await _safe(repo_info.get_languages(await _get_client(), owner, repo))


# ═══════════════════════════════════════════════════════════════════════
# UTILITY TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"read", "repo"}, annotations={"readOnlyHint": True})
async def get_rate_limit() -> str:
    """Check the current GitHub API rate limit status.

    Returns:
        Current rate limit remaining, total, and reset time.
    """
    client = await _get_client()
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


# ═══════════════════════════════════════════════════════════════════════
# WRITE / CODE TOOLS  (tag="write" → hidden via Visibility when MCP_READ_ONLY=true)
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"write"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def create_branch(
    owner: str,
    repo: str,
    branch: str,
    from_ref: str | None = None,
) -> str:
    """Create a new branch in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        branch: Name of the new branch to create (e.g. "feature/my-feature").
        from_ref: Branch name, tag, or commit SHA to branch off from.
                  Defaults to the repo's default branch.
    """
    return await _safe(write_ops.create_branch(await _get_client(), owner, repo, branch, from_ref))


@mcp.tool(tags={"write"}, annotations={"readOnlyHint": False, "destructiveHint": True})
async def push_files(
    owner: str,
    repo: str,
    branch: str,
    files: list[dict],
    message: str,
) -> str:
    """Commit one or more files to a branch in a single atomic commit.

    Use this to create new files, update existing files, or both — all in one commit.
    This is the primary tool for making code changes.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        branch: Target branch to push to (must already exist; use create_branch first).
        files: List of file objects, each with:
               - "path": file path in the repo (e.g. "src/main.py")
               - "content": full UTF-8 text content of the file
        message: Commit message.

    Example files:
        [{"path": "src/app.py", "content": "print('hello')"},
         {"path": "README.md", "content": "# My Project"}]
    """
    return await _safe(write_ops.push_files(await _get_client(), owner, repo, branch, files, message))


@mcp.tool(tags={"write"}, annotations={"readOnlyHint": False, "destructiveHint": True})
async def delete_file(
    owner: str,
    repo: str,
    path: str,
    message: str,
    branch: str,
) -> str:
    """Delete a file from a GitHub repository branch.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: Path of the file to delete (e.g. "src/old_module.py").
        message: Commit message for the deletion.
        branch: Branch to delete the file from.
    """
    return await _safe(write_ops.delete_file(await _get_client(), owner, repo, path, message, branch))


@mcp.tool(tags={"write", "ci"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def list_workflow_runs(
    owner: str,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    """List recent CI/CD workflow runs for a repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        workflow_id: Optional workflow filename (e.g. "ci.yml") or numeric ID to filter by.
        branch: Optional branch name to filter runs by.
        status: Optional status filter: "queued", "in_progress", "completed",
                "action_required", "cancelled", "failure", "neutral", "skipped",
                "stale", "success", "timed_out", "waiting".
        limit: Maximum number of runs to return (default: 10).
    """
    return await _safe(write_ops.list_workflow_runs(
        await _get_client(), owner, repo, workflow_id, branch, status, limit
    ))


@mcp.tool(tags={"write", "ci"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def get_workflow_run_logs(
    owner: str,
    repo: str,
    run_id: int,
    max_chars: int = 20000,
) -> str:
    """Get the logs for a GitHub Actions workflow run, highlighting failed steps.

    Shows a job/step summary at the top, then the full log content of any
    failed steps. If all steps passed, shows all logs. Useful for diagnosing
    why a CI run failed after pushing code.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        run_id: The numeric workflow run ID (from list_workflow_runs).
        max_chars: Maximum log characters to return (default: 20000).
                   Increase if you need more context, but be aware of response size.
    """
    return await _safe(write_ops.get_workflow_run_logs(await _get_client(), owner, repo, run_id, max_chars))


@mcp.tool(tags={"write", "ci"}, annotations={"readOnlyHint": False, "destructiveHint": True})
async def trigger_workflow(
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: dict | None = None,
) -> str:
    """Trigger a workflow_dispatch event to run a CI/CD workflow.

    The workflow must have a 'workflow_dispatch' trigger configured in its YAML.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        workflow_id: Workflow filename (e.g. "ci.yml") or numeric ID.
        ref: Branch or tag name to run the workflow on (e.g. "main").
        inputs: Optional key/value inputs defined in the workflow's workflow_dispatch config.
    """
    return await _safe(write_ops.trigger_workflow(await _get_client(), owner, repo, workflow_id, ref, inputs))


# ═══════════════════════════════════════════════════════════════════════
# PULL REQUEST & ISSUE TOOLS
# Read-only tools (list, get) are tagged {"read", "pr"} — visible in any mode.
# Mutating tools (create, merge, comment, issue) are tagged {"write", "pr"} —
# hidden when MCP_READ_ONLY=true.
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"write", "pr"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
) -> str:
    """Create a new pull request in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        title: PR title.
        head: The branch containing your changes (e.g. "feature/my-feature").
        base: The branch you want to merge into (e.g. "main").
        body: Optional PR description (supports Markdown).
        draft: If True, open as a draft pull request.
    """
    return await _safe(pr_ops.create_pull_request(
        await _get_client(), owner, repo, title, head, base, body, draft
    ))


@mcp.tool(tags={"read", "pr"}, annotations={"readOnlyHint": True})
async def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    head: str | None = None,
    base: str | None = None,
    limit: int = 20,
) -> str:
    """List pull requests in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        state: Filter by state: "open" (default), "closed", or "all".
        head: Filter by head branch (e.g. "feature/my-feature" or "myorg:feature/my-feature").
        base: Filter by base branch (e.g. "main").
        limit: Maximum number of PRs to return (default: 20).
    """
    return await _safe(pr_ops.list_pull_requests(await _get_client(), owner, repo, state, head, base, limit))


@mcp.tool(tags={"read", "pr"}, annotations={"readOnlyHint": True})
async def get_pull_request(
    owner: str,
    repo: str,
    pull_number: int,
) -> str:
    """Get details of a specific pull request including status, commits, and file counts.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        pull_number: The pull request number.
    """
    return await _safe(pr_ops.get_pull_request(await _get_client(), owner, repo, pull_number))


@mcp.tool(tags={"write", "pr"}, annotations={"readOnlyHint": False, "destructiveHint": True})
async def merge_pull_request(
    owner: str,
    repo: str,
    pull_number: int,
    commit_title: str | None = None,
    merge_method: str = "merge",
) -> str:
    """Merge a pull request.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        pull_number: The pull request number to merge.
        commit_title: Optional custom commit title for the merge commit.
        merge_method: Merge strategy: "merge" (default), "squash", or "rebase".
    """
    return await _safe(pr_ops.merge_pull_request(
        await _get_client(), owner, repo, pull_number, commit_title, merge_method
    ))


@mcp.tool(tags={"write", "pr"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def add_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    body: str,
) -> str:
    """Add a comment to a pull request.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        pull_number: The pull request number to comment on.
        body: Comment text (supports Markdown).
    """
    return await _safe(pr_ops.add_pr_comment(await _get_client(), owner, repo, pull_number, body))


@mcp.tool(tags={"write", "pr"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
) -> str:
    """Create a new issue in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        title: Issue title.
        body: Optional issue body (supports Markdown).
        labels: Optional list of label names to apply (e.g. ["bug", "help wanted"]).
    """
    return await _safe(pr_ops.create_issue(await _get_client(), owner, repo, title, body, labels))


# ═══════════════════════════════════════════════════════════════════════
# TODO TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool(tags={"write", "todo"}, annotations={"readOnlyHint": False, "destructiveHint": True})
async def todo_write(todos: list[dict]) -> str:
    """Update the in-session task list for tracking multi-step work.

    Call this at the start of any complex task (3+ steps) and after each step
    completes to keep the list current. Only one task should be "in_progress"
    at a time.

    Args:
        todos: List of task objects. Each must have:
               - "content": task description (str)
               - "status": "pending" | "in_progress" | "completed"

    Example:
        [{"content": "Create branch", "status": "completed"},
         {"content": "Push files",    "status": "in_progress"},
         {"content": "Open PR",       "status": "pending"}]
    """
    return todo_ops.todo_write(todos)


@mcp.tool(tags={"write", "todo"}, annotations={"readOnlyHint": False, "destructiveHint": False})
async def todo_update(index: int, status: str) -> str:
    """Update the status of a single todo item by its 0-based index.

    Use this to check off individual tasks as you complete them, without
    rewriting the full list. Typical pattern per step:
      1. todo_update(i, "in_progress")  ← start the task
      2. ... do the work ...
      3. todo_update(i, "completed")    ← check it off

    Args:
        index: 0-based position of the task in the list.
        status: New status — "pending", "in_progress", or "completed".
    """
    return todo_ops.todo_update(index, status)


@mcp.tool(tags={"read", "todo"}, annotations={"readOnlyHint": True})
async def todo_read() -> str:
    """Read the current in-session task list.

    Returns a formatted summary showing status of all tasks.
    Returns a message if the list is empty.
    """
    return todo_ops.todo_read()


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import warnings
    import uvicorn

    warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    upstash_rest_url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    upstash_rest_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    # MCP_STATELESS=false enables stateful SSE event replay via Redis.
    # Default is true (stateless): survives restarts, no stale session issues.
    # Set to false only when using streaming tools that need resume-on-reconnect.
    stateless = parse_bool(os.environ.get("MCP_STATELESS", "true"), default=True)

    if not stateless and upstash_rest_url and upstash_rest_token:
        # Stateful mode with SSE event replay: clients can resume a dropped SSE
        # stream using Last-Event-ID. Requires Redis. Sessions are in-memory so
        # clients must re-initialise after a server restart.
        from urllib.parse import urlparse
        from redis.asyncio import Redis as AsyncRedis
        from key_value.aio.stores.redis import RedisStore
        from fastmcp.server.event_store import EventStore as FastMCPEventStore

        _upstash_host = urlparse(upstash_rest_url).hostname or upstash_rest_url
        _redis_url = f"rediss://default:{upstash_rest_token}@{_upstash_host}:6379"
        redis_client = AsyncRedis.from_url(_redis_url, decode_responses=True)
        event_store = FastMCPEventStore(storage=RedisStore(client=redis_client))
        app = mcp.http_app(
            transport="streamable-http",
            event_store=event_store,
            stateless_http=False,
        )
        log.info("Starting in stateful mode with Upstash Redis SSE event replay")
        uvicorn.run(app, host=host, port=port, lifespan="on")
    else:
        if not stateless and (not upstash_rest_url or not upstash_rest_token):
            log.warning(
                "MCP_STATELESS=false requires UPSTASH_REDIS_REST_URL and "
                "UPSTASH_REDIS_REST_TOKEN — falling back to stateless mode"
            )
        # Stateless mode (default): new transport per request, survives restarts,
        # no stale session IDs. Redis vars are ignored in this mode.
        mcp.run(
            transport="streamable-http",
            host=host,
            port=port,
            stateless_http=True,
        )
