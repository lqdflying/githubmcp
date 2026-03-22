"""Tests for pr_ops tools: create_pull_request, list/get PR, merge, comment, create_issue."""

import pytest
from src.tools.pr_ops import (
    create_pull_request,
    list_pull_requests,
    get_pull_request,
    merge_pull_request,
    add_pr_comment,
    create_issue,
)


# ── create_pull_request ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_pull_request(mock_client):
    mock_client.create_pull_request.return_value = {
        "number": 7,
        "title": "Add feature X",
        "draft": False,
        "html_url": "https://github.com/owner/repo/pull/7",
    }

    result = await create_pull_request(
        mock_client, "owner", "repo", "Add feature X", "feature/x", "main", body="Details here."
    )

    mock_client.create_pull_request.assert_called_once_with(
        "owner", "repo", "Add feature X", "feature/x", "main", "Details here.", False
    )
    assert "#7" in result
    assert "feature/x" in result
    assert "main" in result
    assert "open" in result


@pytest.mark.asyncio
async def test_create_draft_pull_request(mock_client):
    mock_client.create_pull_request.return_value = {
        "number": 8,
        "title": "WIP: thing",
        "draft": True,
        "html_url": "https://github.com/owner/repo/pull/8",
    }

    result = await create_pull_request(
        mock_client, "owner", "repo", "WIP: thing", "wip/thing", "main", draft=True
    )

    assert "draft" in result
    assert "#8" in result


# ── list_pull_requests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pull_requests(mock_client):
    mock_client.list_pull_requests.return_value = [
        {
            "number": 5,
            "title": "Fix bug",
            "draft": False,
            "head": {"label": "owner:fix/bug"},
            "base": {"label": "owner:main"},
            "user": {"login": "alice"},
            "updated_at": "2024-03-01T12:00:00Z",
            "html_url": "https://github.com/owner/repo/pull/5",
        }
    ]

    result = await list_pull_requests(mock_client, "owner", "repo")

    mock_client.list_pull_requests.assert_called_once_with(
        "owner", "repo", "open", None, None, per_page=20
    )
    assert "#5" in result
    assert "Fix bug" in result
    assert "alice" in result


@pytest.mark.asyncio
async def test_list_pull_requests_empty(mock_client):
    mock_client.list_pull_requests.return_value = []

    result = await list_pull_requests(mock_client, "owner", "repo", state="closed")
    assert "No closed pull requests found" in result


# ── get_pull_request ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_pull_request(mock_client):
    mock_client.get_pull_request.return_value = {
        "number": 3,
        "title": "Refactor auth",
        "state": "open",
        "draft": False,
        "head": {"label": "owner:refactor/auth"},
        "base": {"label": "owner:main"},
        "user": {"login": "bob"},
        "created_at": "2024-02-01T00:00:00Z",
        "mergeable": True,
        "commits": 3,
        "changed_files": 5,
        "additions": 120,
        "deletions": 40,
        "html_url": "https://github.com/owner/repo/pull/3",
        "body": "Refactored the auth module.",
    }

    result = await get_pull_request(mock_client, "owner", "repo", 3)

    assert "#3" in result
    assert "Refactor auth" in result
    assert "bob" in result
    assert "yes" in result  # mergeable
    assert "+120" in result


# ── merge_pull_request ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_pull_request(mock_client):
    mock_client.merge_pull_request.return_value = {
        "sha": "abcdef1234567890",
        "message": "Pull Request successfully merged",
    }

    result = await merge_pull_request(mock_client, "owner", "repo", 5)

    mock_client.merge_pull_request.assert_called_once_with("owner", "repo", 5, None, "merge")
    assert "Merged PR #5" in result
    assert "abcdef1" in result


@pytest.mark.asyncio
async def test_merge_pull_request_squash(mock_client):
    mock_client.merge_pull_request.return_value = {"sha": "1111abc", "message": "Squash merged"}

    result = await merge_pull_request(
        mock_client, "owner", "repo", 9, commit_title="Squash all things", merge_method="squash"
    )

    mock_client.merge_pull_request.assert_called_once_with(
        "owner", "repo", 9, "Squash all things", "squash"
    )
    assert "squash" in result


# ── add_pr_comment ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_pr_comment(mock_client):
    mock_client.create_issue_comment.return_value = {
        "id": 999,
        "html_url": "https://github.com/owner/repo/pull/3#issuecomment-999",
    }

    result = await add_pr_comment(mock_client, "owner", "repo", 3, "LGTM!")

    mock_client.create_issue_comment.assert_called_once_with("owner", "repo", 3, "LGTM!")
    assert "PR #3" in result
    assert "999" in result


# ── create_issue ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_issue(mock_client):
    mock_client.create_issue.return_value = {
        "number": 42,
        "title": "Something broke",
        "html_url": "https://github.com/owner/repo/issues/42",
        "labels": [{"name": "bug"}, {"name": "urgent"}],
    }

    result = await create_issue(
        mock_client, "owner", "repo", "Something broke", "Details.", labels=["bug", "urgent"]
    )

    mock_client.create_issue.assert_called_once_with(
        "owner", "repo", "Something broke", "Details.", ["bug", "urgent"]
    )
    assert "#42" in result
    assert "bug" in result
    assert "urgent" in result


@pytest.mark.asyncio
async def test_create_issue_no_labels(mock_client):
    mock_client.create_issue.return_value = {
        "number": 10,
        "title": "Simple issue",
        "html_url": "https://github.com/owner/repo/issues/10",
        "labels": [],
    }

    result = await create_issue(mock_client, "owner", "repo", "Simple issue")

    assert "#10" in result
    assert "Simple issue" in result
