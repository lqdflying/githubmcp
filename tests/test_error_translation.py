"""Regression test: GitHubAPIError should surface as ToolError, not a masked generic error.

When mask_error_details=True, FastMCP converts unhandled exceptions into opaque
"Error calling tool" messages.  Tool handlers must translate expected domain errors
(GitHubAPIError) into ToolError before FastMCP's generic mask sees them.
"""

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.github_client import GitHubAPIError, GitHubClient


@pytest.fixture
def server_module(monkeypatch):
    """Load server.py with token auth and a fake GitHub client (no network)."""
    monkeypatch.setenv("MCP_AUTH_MODE", "token")
    monkeypatch.setenv("MCP_API_TOKEN", "test-api-token-integration")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)

    sys.modules.pop("server", None)
    import server

    importlib.reload(server)

    mock_client = MagicMock(spec=GitHubClient)
    mock_client.get_file_content = AsyncMock(
        side_effect=GitHubAPIError(404, "Resource not found.")
    )
    server._github_client = mock_client
    server._mock_client = mock_client
    return server


@pytest.mark.asyncio
async def test_server_read_file_uses_safe_wrapper(server_module):
    """Integration: real server.mcp.read_file must use server._safe, not manual ToolError.

    Would fail with a generic "Error calling tool" if _safe(...) were removed from
    the read_file handler while mask_error_details=True stays enabled.
    """
    with pytest.raises(ToolError) as exc_info:
        await server_module.mcp.call_tool(
            "read_file",
            {"owner": "owner", "repo": "repo", "path": "missing.py"},
        )

    server_module._mock_client.get_file_content.assert_awaited_once_with(
        "owner", "repo", "missing.py", None
    )
    assert "Resource not found." in str(exc_info.value)
    assert "Error calling tool" not in str(exc_info.value)


@pytest.fixture
def error_safe_mcp():
    """FastMCP server with mask_error_details=True."""
    return FastMCP("test-error-translation", mask_error_details=True)


@pytest.mark.asyncio
async def test_github_api_error_become_tool_error(error_safe_mcp):
    """Tool handler wrapping GitHubAPIError → ToolError preserves the message."""
    tool_called = False

    @error_safe_mcp.tool()
    async def read_file() -> str:
        nonlocal tool_called
        tool_called = True
        try:
            raise GitHubAPIError(404, "Resource not found.")
        except GitHubAPIError as e:
            raise ToolError(str(e))

    with pytest.raises(ToolError) as exc_info:
        await error_safe_mcp.call_tool("read_file", {})

    assert tool_called, "Tool was never invoked"
    assert "Resource not found." in str(exc_info.value)


@pytest.mark.asyncio
async def test_github_api_error_403_write_hint_surfaces(error_safe_mcp):
    """GitHubAPIError(403) with permission hint should flow through."""
    tool_called = False

    @error_safe_mcp.tool()
    async def push_files() -> str:
        nonlocal tool_called
        tool_called = True
        try:
            raise GitHubAPIError(
                403,
                "Access denied. Write operations require additional PAT permissions.",
            )
        except GitHubAPIError as e:
            raise ToolError(str(e))

    with pytest.raises(ToolError) as exc_info:
        await error_safe_mcp.call_tool("push_files", {})

    assert tool_called, "Tool was never invoked"
    assert "permissions" in str(exc_info.value)


@pytest.mark.asyncio
async def test_unexpected_error_still_masked(error_safe_mcp):
    """Non-GitHubAPIError exceptions should get the generic mask."""
    tool_called = False

    @error_safe_mcp.tool()
    async def crash_tool() -> str:
        nonlocal tool_called
        tool_called = True
        raise ValueError("internal bug")

    with pytest.raises(Exception) as exc_info:
        await error_safe_mcp.call_tool("crash_tool", {})

    assert tool_called, "Tool was never invoked"
    msg = str(exc_info.value)
    assert "internal bug" not in msg.lower()
    assert "error" in msg.lower()
