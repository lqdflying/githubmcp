"""GitHub Repo Reader MCP Server.

Provides MCP tools for reading GitHub repository contents, searching code,
viewing git history, and exploring repo structure — all via GitHub PAT auth.
"""

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.auth import setup_auth, parse_bool
from src.github_client import GitHubClient, GitHubAPIError
from src.tools import file_ops, code_search, git_ops, repo_info, write_ops, pr_ops, todo_ops

# ── Read-only mode ────────────────────────────────────────────────────
# When MCP_READ_ONLY=true, all write/PR/CI tools are skipped at registration
# time. Use this when your GITHUB_PAT only has read permissions.
_READ_ONLY = parse_bool(os.environ.get("MCP_READ_ONLY", "false"), default=False)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mcp")
logger = logging.getLogger(__name__)

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

    if _READ_ONLY:
        print(
            "Running in READ-ONLY mode (MCP_READ_ONLY=true): "
            "write/PR/CI tools are disabled.",
            file=sys.stderr,
        )
    else:
        print(
            "Running in READ+WRITE mode. "
            "Ensure GITHUB_PAT has write permissions (classic: 'repo'; "
            "fine-grained: Contents+PR+Actions write). "
            "Set MCP_READ_ONLY=true to disable write tools.",
            file=sys.stderr,
        )

    yield

    await _github_client.close()


def _get_client() -> GitHubClient:
    if _github_client is None:
        raise RuntimeError("GitHub client not initialized. Server lifespan not started.")
    return _github_client


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
)


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
    return await repo_info.get_repo_structure(
        _get_client(), owner, repo, ref, max_depth, path_filter
    )


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


# ── Write permission error helper ────────────────────────────────────

_WRITE_PERM_HINT = (
    "GitHub API returned 403 (permission denied).\n"
    "Write tools require additional PAT permissions:\n"
    "  • Classic token: 'repo' scope\n"
    "  • Fine-grained token: Contents: Read+Write, Metadata: Read,\n"
    "    Pull requests: Read+Write, Actions: Read+Write\n"
    "Or set MCP_READ_ONLY=true to disable write tools entirely."
)



# ═══════════════════════════════════════════════════════════════════════
# WRITE / CODE TOOLS
# ═══════════════════════════════════════════════════════════════════════

# _write_tool registers an MCP tool only when not in read-only mode.
# If MCP_READ_ONLY=true, the decorated function is simply not registered
# and the tool is invisible to MCP clients.
_write_tool = (lambda fn: fn) if _READ_ONLY else mcp.tool()


@_write_tool
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
    return await write_ops.create_branch(_get_client(), owner, repo, branch, from_ref)


@_write_tool
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
    return await write_ops.push_files(_get_client(), owner, repo, branch, files, message)


@_write_tool
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
    return await write_ops.delete_file(_get_client(), owner, repo, path, message, branch)


@_write_tool
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
    return await write_ops.list_workflow_runs(
        _get_client(), owner, repo, workflow_id, branch, status, limit
    )


@_write_tool
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
    return await write_ops.get_workflow_run_logs(_get_client(), owner, repo, run_id, max_chars)


@_write_tool
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
    return await write_ops.trigger_workflow(_get_client(), owner, repo, workflow_id, ref, inputs)


# ═══════════════════════════════════════════════════════════════════════
# PULL REQUEST & ISSUE TOOLS
# ═══════════════════════════════════════════════════════════════════════


@_write_tool
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
    return await pr_ops.create_pull_request(
        _get_client(), owner, repo, title, head, base, body, draft
    )


@_write_tool
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
    return await pr_ops.list_pull_requests(_get_client(), owner, repo, state, head, base, limit)


@_write_tool
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
    return await pr_ops.get_pull_request(_get_client(), owner, repo, pull_number)


@_write_tool
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
    return await pr_ops.merge_pull_request(
        _get_client(), owner, repo, pull_number, commit_title, merge_method
    )


@_write_tool
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
    return await pr_ops.add_pr_comment(_get_client(), owner, repo, pull_number, body)


@_write_tool
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
    return await pr_ops.create_issue(_get_client(), owner, repo, title, body, labels)


# ═══════════════════════════════════════════════════════════════════════
# TODO TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
