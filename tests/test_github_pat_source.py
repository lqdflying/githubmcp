"""Tests for selecting GitHub API credentials independently from MCP auth."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from src.github_client import GitHubAPIError, GitHubClient


@pytest.fixture
def import_server(monkeypatch):
    previous_module = sys.modules.get("server")

    def _load(
        *,
        token_mode: str = "env",
        github_pat: str | None = None,
        header: str = "X-GitHub-PAT",
        validate_request_pat: str = "false",
        cache_max_size: str = "128",
        cache_ttl_seconds: str = "1800",
    ):
        monkeypatch.setenv("MCP_AUTH_MODE", "token")
        monkeypatch.setenv("MCP_API_TOKEN", "test-api-token")
        monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
        monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN_MODE", token_mode)
        monkeypatch.setenv("GITHUB_PAT_HEADER", header)
        monkeypatch.setenv("GITHUB_VALIDATE_REQUEST_PAT", validate_request_pat)
        monkeypatch.setenv("GITHUB_CLIENT_CACHE_MAX_SIZE", cache_max_size)
        monkeypatch.setenv("GITHUB_CLIENT_CACHE_TTL_SECONDS", cache_ttl_seconds)
        if github_pat is None:
            monkeypatch.delenv("GITHUB_PAT", raising=False)
        else:
            monkeypatch.setenv("GITHUB_PAT", github_pat)

        sys.modules.pop("server", None)
        import server

        return importlib.reload(server)

    try:
        yield _load
    finally:
        if previous_module is not None:
            sys.modules["server"] = previous_module
        else:
            sys.modules.pop("server", None)


def _request_with_headers(headers: dict[str, str]):
    return SimpleNamespace(headers=headers)


@pytest.mark.asyncio
async def test_env_mode_uses_server_github_client(import_server):
    server = import_server(token_mode="env", github_pat="env-token")
    env_client = MagicMock(spec=GitHubClient)
    server._github_client = env_client

    assert await server._get_client() is env_client


@pytest.mark.asyncio
async def test_invalid_github_token_mode_exits(import_server):
    server = import_server(token_mode="invalid", github_pat="env-token")

    with pytest.raises(SystemExit):
        await server._get_client()


@pytest.mark.asyncio
async def test_request_or_env_mode_uses_request_pat_first(import_server, monkeypatch):
    server = import_server(
        token_mode="request_or_env",
        github_pat="env-token",
        header="X-Test-GitHub-PAT",
    )
    env_client = MagicMock(spec=GitHubClient)
    request_client = MagicMock(spec=GitHubClient)
    created_tokens: list[str] = []

    server._github_client = env_client
    monkeypatch.setattr(
        server,
        "GitHubClient",
        lambda token: created_tokens.append(token) or request_client,
    )
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "Bearer request-token"}),
    )

    assert await server._get_client() is request_client
    assert await server._get_client() is request_client
    assert created_tokens == ["request-token"]


@pytest.mark.asyncio
async def test_request_or_env_mode_falls_back_to_env_client(import_server, monkeypatch):
    server = import_server(token_mode="request_or_env", github_pat="env-token")
    env_client = MagicMock(spec=GitHubClient)

    server._github_client = env_client
    monkeypatch.setattr(
        server,
        "get_http_request",
        MagicMock(side_effect=RuntimeError("No active HTTP request found.")),
    )

    assert await server._get_client() is env_client


@pytest.mark.asyncio
async def test_request_or_env_mode_treats_whitespace_header_as_missing(import_server, monkeypatch):
    server = import_server(token_mode="request_or_env", github_pat="env-token")
    env_client = MagicMock(spec=GitHubClient)

    server._github_client = env_client
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-GitHub-PAT": "   "}),
    )

    assert await server._get_client() is env_client


@pytest.mark.asyncio
async def test_request_mode_requires_github_pat_header(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({}),
    )

    with pytest.raises(ToolError) as exc_info:
        await server._get_client()

    msg = str(exc_info.value)
    assert "Missing GitHub PAT header: X-Test-GitHub-PAT" in msg
    assert "github_pat_" not in msg


@pytest.mark.asyncio
async def test_request_mode_treats_whitespace_header_as_missing(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "   "}),
    )

    with pytest.raises(ToolError) as exc_info:
        await server._get_client()

    assert "Missing GitHub PAT header: X-Test-GitHub-PAT" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_pat_header_cannot_be_authorization(import_server):
    server = import_server(token_mode="request", header="Authorization")

    with pytest.raises(SystemExit):
        await server._get_client()


@pytest.mark.asyncio
async def test_request_or_env_without_any_pat_errors_clearly(import_server, monkeypatch):
    server = import_server(token_mode="request_or_env", header="X-Test-GitHub-PAT")
    monkeypatch.setattr(
        server,
        "get_http_request",
        MagicMock(side_effect=RuntimeError("No active HTTP request found.")),
    )

    with pytest.raises(ToolError) as exc_info:
        await server._get_client()

    assert "No GitHub PAT is available" in str(exc_info.value)
    assert "X-Test-GitHub-PAT" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_client_cache_uses_token_hash_not_plaintext(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    request_client = MagicMock(spec=GitHubClient)

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "github_pat_secret"}),
    )

    assert await server._get_client() is request_client
    cache_keys = list(server._request_github_clients.keys())
    assert len(cache_keys) == 1
    assert cache_keys[0] != "github_pat_secret"
    assert len(cache_keys[0]) == 64


@pytest.mark.asyncio
async def test_request_client_cache_evicts_lru_and_closes_client(import_server, monkeypatch):
    server = import_server(
        token_mode="request",
        header="X-Test-GitHub-PAT",
        cache_max_size="2",
    )
    clients: dict[str, MagicMock] = {}

    def _make_client(token: str):
        client = MagicMock(spec=GitHubClient)
        client.close = AsyncMock()
        clients[token] = client
        return client

    current_token = {"value": "token-1"}
    monkeypatch.setattr(server, "GitHubClient", _make_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": current_token["value"]}),
    )

    assert await server._get_client() is clients["token-1"]
    current_token["value"] = "token-2"
    assert await server._get_client() is clients["token-2"]
    current_token["value"] = "token-1"
    assert await server._get_client() is clients["token-1"]
    current_token["value"] = "token-3"
    assert await server._get_client() is clients["token-3"]

    assert len(server._request_github_clients) == 2
    clients["token-1"].close.assert_not_awaited()
    clients["token-2"].close.assert_awaited_once()
    clients["token-3"].close.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_client_cache_expires_idle_clients(import_server, monkeypatch):
    server = import_server(
        token_mode="request",
        header="X-Test-GitHub-PAT",
        cache_ttl_seconds="1",
    )
    clients: list[MagicMock] = []
    now = {"value": 0.0}

    def _make_client(token: str):
        client = MagicMock(spec=GitHubClient)
        client.close = AsyncMock()
        clients.append(client)
        return client

    monkeypatch.setattr(server, "GitHubClient", _make_client)
    monkeypatch.setattr(server.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "token-1"}),
    )

    first_client = await server._get_client()
    now["value"] = 2.0
    second_client = await server._get_client()

    assert first_client is not second_client
    clients[0].close.assert_awaited_once()
    clients[1].close.assert_not_awaited()
    assert len(server._request_github_clients) == 1


@pytest.mark.asyncio
async def test_request_pat_validate_on_first_use_success(import_server, monkeypatch):
    server = import_server(
        token_mode="request",
        header="X-Test-GitHub-PAT",
        validate_request_pat="true",
    )
    request_client = MagicMock(spec=GitHubClient)
    request_client.validate_token = AsyncMock(return_value={"login": "octocat"})
    request_client.close = AsyncMock()

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "request-token"}),
    )

    assert await server._get_client() is request_client
    assert await server._get_client() is request_client

    request_client.validate_token.assert_awaited_once()
    request_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_pat_validate_on_first_use_failure(import_server, monkeypatch):
    server = import_server(
        token_mode="request",
        header="X-Test-GitHub-PAT",
        validate_request_pat="true",
    )
    request_client = MagicMock(spec=GitHubClient)
    request_client.validate_token = AsyncMock(
        side_effect=GitHubAPIError(401, "Invalid or expired GitHub token.")
    )
    request_client.close = AsyncMock()

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "github_pat_secret"}),
    )

    with pytest.raises(ToolError) as exc_info:
        await server._get_client()

    msg = str(exc_info.value)
    assert "GitHub PAT from X-Test-GitHub-PAT is invalid or unauthorized" in msg
    assert "github_pat_secret" not in msg
    request_client.close.assert_awaited_once()
    assert server._request_github_clients == {}


@pytest.mark.asyncio
async def test_request_mode_lifespan_does_not_require_env_pat(import_server):
    server = import_server(token_mode="request")

    async with server.lifespan(server.mcp):
        assert server._github_client is None


@pytest.mark.asyncio
async def test_env_mode_lifespan_still_requires_env_pat(import_server):
    server = import_server(token_mode="env")

    with pytest.raises(SystemExit):
        async with server.lifespan(server.mcp):
            pass


@pytest.mark.asyncio
async def test_request_mode_lifespan_validates_cache_settings(import_server):
    server = import_server(token_mode="request", cache_max_size="0")

    with pytest.raises(SystemExit):
        async with server.lifespan(server.mcp):
            pass


@pytest.mark.asyncio
async def test_env_mode_lifespan_validates_env_pat(import_server, monkeypatch):
    server = import_server(token_mode="env", github_pat="env-token")
    env_client = MagicMock(spec=GitHubClient)
    env_client.validate_token = AsyncMock(return_value={"login": "octocat"})
    env_client.close = AsyncMock()

    monkeypatch.setattr(server, "GitHubClient", lambda token: env_client)

    async with server.lifespan(server.mcp):
        env_client.validate_token.assert_awaited_once()

    env_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_closes_cached_request_clients(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    request_client = MagicMock(spec=GitHubClient)
    request_client.close = AsyncMock()

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "request-token"}),
    )

    async with server.lifespan(server.mcp):
        assert await server._get_client() is request_client

    request_client.close.assert_awaited_once()
    assert server._request_github_clients == {}


@pytest.mark.asyncio
async def test_lifespan_closes_cached_request_clients_after_error(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    request_client = MagicMock(spec=GitHubClient)
    request_client.close = AsyncMock()

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "request-token"}),
    )

    with pytest.raises(RuntimeError):
        async with server.lifespan(server.mcp):
            assert await server._get_client() is request_client
            raise RuntimeError("server stopped")

    request_client.close.assert_awaited_once()
    assert server._request_github_clients == {}


@pytest.mark.asyncio
async def test_tool_call_uses_request_specific_github_client(import_server, monkeypatch):
    server = import_server(token_mode="request", header="X-Test-GitHub-PAT")
    request_client = MagicMock(spec=GitHubClient)
    request_client.get_file_content = AsyncMock(return_value="hello\n")

    monkeypatch.setattr(server, "GitHubClient", lambda token: request_client)
    monkeypatch.setattr(
        server,
        "get_http_request",
        lambda: _request_with_headers({"X-Test-GitHub-PAT": "request-token"}),
    )

    await server.mcp.call_tool(
        "read_file",
        {"owner": "owner", "repo": "repo", "path": "README.md"},
    )

    request_client.get_file_content.assert_awaited_once_with(
        "owner", "repo", "README.md", None
    )
