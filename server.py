"""GitHub Repo Reader MCP Server.

Provides MCP tools for reading GitHub repository contents, searching code,
viewing git history, and exploring repo structure — all via GitHub PAT auth.
"""

import hmac
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.cimd import CIMDClientManager
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.github_client import GitHubClient, GitHubAPIError
from src.tools import file_ops, code_search, git_ops, repo_info

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

    yield

    await _github_client.close()


def _get_client() -> GitHubClient:
    if _github_client is None:
        raise RuntimeError("GitHub client not initialized. Server lifespan not started.")
    return _github_client


# ── Authentication ───────────────────────────────────────────────────

# ── RFC 8252 loopback-aware CIMD manager ─────────────────────────────
# VS Code's CIMD document (https://vscode.dev/oauth/client-metadata.json) lists
# a fixed loopback port (e.g. http://127.0.0.1:33418/) but VS Code sends a
# dynamic port at runtime (e.g. http://127.0.0.1:62621/). Per RFC 8252 §7.3,
# the port MUST be ignored for loopback redirect URIs. This manager normalizes
# fixed loopback ports to wildcard patterns before FastMCP validates them.

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _normalize_loopback_redirect_uris(redirect_uris: list[str]) -> list[str]:
    """Replace fixed loopback ports with :* wildcards per RFC 8252."""
    normalized = []
    for uri in redirect_uris:
        parsed = urlparse(uri.rstrip("/"))
        host = (parsed.hostname or "").lower()
        if host in _LOOPBACK_HOSTS and parsed.scheme == "http" and parsed.port:
            normalized.append(f"http://{host}:*/")
        else:
            normalized.append(uri)
    return normalized


class _RFC8252CIMDManager(CIMDClientManager):
    """CIMD manager that normalizes fixed loopback ports to wildcards (RFC 8252)."""

    async def get_client(self, client_id_url: str):
        client = await super().get_client(client_id_url)
        if client is None or client.cimd_document is None:
            return client

        doc = client.cimd_document
        if not doc.redirect_uris:
            return client

        normalized = _normalize_loopback_redirect_uris(doc.redirect_uris)
        if normalized != list(doc.redirect_uris):
            new_doc = doc.model_copy(update={"redirect_uris": normalized})
            client = client.model_copy(update={"cimd_document": new_doc})

        return client


# GitHub child-to-parent scope mapping.
# GitHub App tokens return only a broad parent scope (or nothing) via X-OAuth-Scopes.
# Normalise any child scope in GITHUB_OAUTH_SCOPES to its parent so the token
# check always uses the scope GitHub actually reports.
_GITHUB_CHILD_TO_PARENT: dict[str, str] = {
    "read:user": "user",
    "user:email": "user",
    "user:follow": "user",
    "public_repo": "repo",
    "repo:status": "repo",
    "repo:deployment": "repo",
    "repo:invite": "repo",
    "security_events": "repo",
    "read:org": "admin:org",
    "write:org": "admin:org",
    "read:repo_hook": "write:repo_hook",
    "write:repo_hook": "admin:repo_hook",
}


def _normalize_oauth_scopes(scopes: list[str]) -> list[str]:
    """Map child scopes to their GitHub parent scope, removing duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for s in scopes:
        parent = _GITHUB_CHILD_TO_PARENT.get(s, s)
        if parent not in seen:
            seen.add(parent)
            result.append(parent)
    return result


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_bool(raw: str, default: bool = False) -> bool:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


class TokenOrGitHubOAuthProvider(GitHubProvider):
    """Accept either a shared static token or GitHub OAuth tokens.

    This keeps existing automation that uses MCP_API_TOKEN while enabling
    Power Automate OAuth flows on the same MCP endpoint.
    """

    def __init__(
        self,
        *,
        mcp_api_token: str | None,
        allow_static_token: bool,
        allowed_github_logins: set[str] | None = None,
        audit_logging_enabled: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mcp_api_token = mcp_api_token
        self._allow_static_token = allow_static_token
        self._allowed_github_logins = {login.lower() for login in (allowed_github_logins or set())}
        self._audit_logging_enabled = audit_logging_enabled

        # Replace the CIMD manager with an RFC 8252-aware version that:
        # 1. Normalizes fixed loopback ports to wildcards (RFC 8252 §7.3)
        # 2. Sets default_scope so CIMD clients that don't declare a scope
        #    (e.g. VS Code) are allowed to request the server's required scopes.
        if self._cimd_manager is not None:
            default_scope = " ".join(self.required_scopes) if self.required_scopes else None
            self._cimd_manager = _RFC8252CIMDManager(
                enable_cimd=True,
                default_scope=default_scope,
                allowed_redirect_uri_patterns=self._allowed_client_redirect_uris,
            )

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._allow_static_token and self._mcp_api_token and hmac.compare_digest(token, self._mcp_api_token):
            if self._audit_logging_enabled:
                log.info("AUTH success method=token")
            return AccessToken(
                token=token,
                client_id="mcp-token-client",
                scopes=list(self.required_scopes) if self.required_scopes else ["read"],
                claims={"auth_mode": "static_token"},
            )

        access_token = await super().verify_token(token)
        if access_token is None:
            if self._audit_logging_enabled:
                log.warning("AUTH failed method=oauth_or_token reason=invalid_or_expired")
            return None

        if not self._allowed_github_logins:
            if self._audit_logging_enabled:
                login = access_token.claims.get("login")
                login_label = login if isinstance(login, str) else "unknown"
                log.info(f"AUTH success method=oauth login={login_label}")
            return access_token

        login = access_token.claims.get("login")
        if isinstance(login, str) and login.lower() in self._allowed_github_logins:
            if self._audit_logging_enabled:
                log.info(f"AUTH success method=oauth login={login}")
            return access_token

        if self._audit_logging_enabled:
            blocked_login = login if isinstance(login, str) else "unknown"
            log.warning(
                f"AUTH rejected method=oauth login={blocked_login} reason=login_not_allowlisted"
            )

        return None


_auth_mode = os.environ.get("MCP_AUTH_MODE", "both").strip().lower()
_valid_auth_modes = {"token", "oauth", "both"}
if _auth_mode not in _valid_auth_modes:
    print(
        "ERROR: MCP_AUTH_MODE must be one of: token, oauth, both.",
        file=sys.stderr,
    )
    sys.exit(1)

_need_token_auth = _auth_mode in {"token", "both"}
_need_oauth_auth = _auth_mode in {"oauth", "both"}
_auth_audit_logging_enabled = _parse_bool(os.environ.get("MCP_AUTH_AUDIT_LOG", "true"), True)

_mcp_api_token = os.environ.get("MCP_API_TOKEN", "").strip()
if _need_token_auth and not _mcp_api_token:
    print("ERROR: MCP_API_TOKEN environment variable is required for token auth mode.", file=sys.stderr)
    sys.exit(1)

_github_client_id = os.environ.get("GITHUB_CLIENT_ID", "").strip()
_github_client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
_base_url = os.environ.get("BASE_URL", "").strip()
_github_oauth_scopes = _normalize_oauth_scopes(_split_csv(os.environ.get("GITHUB_OAUTH_SCOPES", "user")))
_allowed_github_logins = set(_split_csv(os.environ.get("ALLOWED_GITHUB_LOGINS", "")))

_oauth_vars = {
    "GITHUB_CLIENT_ID": _github_client_id,
    "GITHUB_CLIENT_SECRET": _github_client_secret,
    "BASE_URL": _base_url,
}
_configured_oauth_vars = [name for name, value in _oauth_vars.items() if value]

if _need_oauth_auth:
    missing = [name for name, value in _oauth_vars.items() if not value]
    if missing:
        print(
            "ERROR: GitHub OAuth is enabled but missing required environment variables: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)
elif _configured_oauth_vars and len(_configured_oauth_vars) != len(_oauth_vars):
    missing = [name for name, value in _oauth_vars.items() if not value]
    print(
        "WARNING: GitHub OAuth variables are partially configured but OAuth is disabled by MCP_AUTH_MODE. "
        f"Ignored variables are missing: {', '.join(missing)}",
        file=sys.stderr,
    )

if _need_oauth_auth:
    _auth = TokenOrGitHubOAuthProvider(
        mcp_api_token=_mcp_api_token if _need_token_auth else None,
        allow_static_token=_need_token_auth,
        allowed_github_logins=_allowed_github_logins,
        audit_logging_enabled=_auth_audit_logging_enabled,
        client_id=_github_client_id,
        client_secret=_github_client_secret,
        base_url=_base_url,
        required_scopes=_github_oauth_scopes,
    )
else:
    def _validate_static_token(token: str) -> bool:
        valid = hmac.compare_digest(token, _mcp_api_token)
        if _auth_audit_logging_enabled:
            if valid:
                log.info("AUTH success method=token")
            else:
                log.warning("AUTH failed method=token reason=invalid_or_expired")
        return valid

    _auth = DebugTokenVerifier(
        validate=_validate_static_token,
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
    stateless = _parse_bool(os.environ.get("MCP_STATELESS", "true"), default=True)

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
