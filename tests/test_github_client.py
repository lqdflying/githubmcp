"""Tests for GitHubClient at the HTTP boundary (real request construction, mocked transport)."""

import json

import httpx
import pytest

from src.github_client import GitHubClient

# Dispatch response body under REST API version 2026-03-10:
# https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
_DISPATCH_RUN = {
    "workflow_run_id": 987654321,
    "run_url": "https://api.github.com/repos/owner/repo/actions/runs/987654321",
    "html_url": "https://github.com/owner/repo/actions/runs/987654321",
}


@pytest.mark.asyncio
async def test_trigger_workflow_sends_api_version_and_returns_run(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_DISPATCH_RUN)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "src.github_client.httpx.AsyncClient",
        lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    client = GitHubClient("test-token")
    try:
        run = await client.trigger_workflow("owner", "repo", "ci.yml", "main", {"env": "prod"})
    finally:
        await client.close()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert (
        str(request.url)
        == "https://api.github.com/repos/owner/repo/actions/workflows/ci.yml/dispatches"
    )
    # Supported versions are listed by GET https://api.github.com/versions
    assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert json.loads(request.content) == {"ref": "main", "inputs": {"env": "prod"}}
    assert run == _DISPATCH_RUN
