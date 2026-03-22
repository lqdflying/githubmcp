"""Tests for write_ops tools: create_branch, push_files, delete_file, workflow ops."""

import pytest
from unittest.mock import AsyncMock
from src.tools.write_ops import create_branch, push_files, delete_file, list_workflow_runs, trigger_workflow


# ── create_branch ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_branch_from_default(mock_client):
    mock_client.get_repo.return_value = {"default_branch": "main"}
    mock_client.get_ref.return_value = {"object": {"sha": "abc1234567890"}}
    mock_client.create_ref.return_value = {}

    result = await create_branch(mock_client, "owner", "repo", "feature/new-feature")

    mock_client.get_repo.assert_called_once_with("owner", "repo")
    mock_client.create_ref.assert_called_once_with(
        "owner", "repo", "refs/heads/feature/new-feature", "abc1234567890"
    )
    assert "feature/new-feature" in result
    assert "abc1234" in result


@pytest.mark.asyncio
async def test_create_branch_from_ref(mock_client):
    mock_client.get_ref.return_value = {"object": {"sha": "deadbeef1234"}}
    mock_client.create_ref.return_value = {}

    result = await create_branch(mock_client, "owner", "repo", "hotfix/bug", from_ref="main")

    mock_client.get_repo.assert_not_called()
    mock_client.create_ref.assert_called_once_with(
        "owner", "repo", "refs/heads/hotfix/bug", "deadbeef1234"
    )
    assert "hotfix/bug" in result
    assert "main" in result


@pytest.mark.asyncio
async def test_create_branch_from_commit_sha(mock_client):
    from src.github_client import GitHubAPIError

    # get_ref raises (not a branch/tag), falls back to get_commit
    mock_client.get_ref.side_effect = GitHubAPIError(404, "Not found")
    mock_client.get_commit.return_value = {"sha": "cafe5678abcd"}
    mock_client.create_ref.return_value = {}

    result = await create_branch(mock_client, "owner", "repo", "fix/from-sha", from_ref="cafe5678abcd")

    mock_client.create_ref.assert_called_once_with(
        "owner", "repo", "refs/heads/fix/from-sha", "cafe5678abcd"
    )
    assert "fix/from-sha" in result


# ── push_files ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_files_single_file(mock_client):
    mock_client.get_ref.return_value = {"object": {"sha": "parent123"}}
    mock_client.get_commit.return_value = {"tree": {"sha": "basetree456"}}
    mock_client.create_blob.return_value = {"sha": "blob789"}
    mock_client.create_tree.return_value = {"sha": "newtree111"}
    mock_client.create_commit_object.return_value = {"sha": "newcommit222"}
    mock_client.update_ref.return_value = {}

    files = [{"path": "src/app.py", "content": "print('hello')"}]
    result = await push_files(mock_client, "owner", "repo", "main", files, "Add app.py")

    mock_client.create_blob.assert_called_once_with("owner", "repo", "print('hello')", encoding="utf-8")
    mock_client.create_tree.assert_called_once_with(
        "owner", "repo",
        [{"path": "src/app.py", "mode": "100644", "type": "blob", "sha": "blob789"}],
        base_tree="basetree456",
    )
    mock_client.create_commit_object.assert_called_once_with(
        "owner", "repo", "Add app.py", "newtree111", ["parent123"]
    )
    mock_client.update_ref.assert_called_once_with("owner", "repo", "heads/main", "newcommit222")
    assert "newcommit" in result or "newcom" in result
    assert "1 file" in result
    assert "src/app.py" in result


@pytest.mark.asyncio
async def test_push_files_multiple(mock_client):
    mock_client.get_ref.return_value = {"object": {"sha": "parent"}}
    mock_client.get_commit.return_value = {"tree": {"sha": "base"}}
    mock_client.create_blob.side_effect = [{"sha": "b1"}, {"sha": "b2"}]
    mock_client.create_tree.return_value = {"sha": "t1"}
    mock_client.create_commit_object.return_value = {"sha": "c1234567"}
    mock_client.update_ref.return_value = {}

    files = [
        {"path": "a.py", "content": "a"},
        {"path": "b.py", "content": "b"},
    ]
    result = await push_files(mock_client, "owner", "repo", "feat", files, "Two files")

    assert mock_client.create_blob.call_count == 2
    assert "2 file" in result
    assert "a.py" in result
    assert "b.py" in result


@pytest.mark.asyncio
async def test_push_files_empty_raises(mock_client):
    with pytest.raises(ValueError, match="files list must not be empty"):
        await push_files(mock_client, "owner", "repo", "main", [], "Empty")


# ── delete_file ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_file_success(mock_client):
    mock_client.get_contents.return_value = {"sha": "filesha123", "type": "file"}
    mock_client.delete_contents.return_value = {}

    result = await delete_file(mock_client, "owner", "repo", "old.py", "Remove old.py", "main")

    mock_client.get_contents.assert_called_once_with("owner", "repo", "old.py", ref="main")
    mock_client.delete_contents.assert_called_once_with(
        "owner", "repo", "old.py", "Remove old.py", "filesha123", "main"
    )
    assert "old.py" in result
    assert "main" in result


@pytest.mark.asyncio
async def test_delete_file_directory_raises(mock_client):
    from src.github_client import GitHubAPIError

    mock_client.get_contents.return_value = [{"name": "file.py"}]  # list = directory

    with pytest.raises(GitHubAPIError) as exc_info:
        await delete_file(mock_client, "owner", "repo", "src/", "Delete dir", "main")
    assert exc_info.value.status_code == 400


# ── list_workflow_runs ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_workflow_runs(mock_client):
    mock_client.list_workflow_runs.return_value = {
        "total_count": 2,
        "workflow_runs": [
            {
                "run_number": 42,
                "name": "CI",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "run_started_at": "2024-01-01T10:00:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/42",
            },
            {
                "run_number": 41,
                "name": "CI",
                "head_branch": "feature/x",
                "status": "in_progress",
                "conclusion": None,
                "run_started_at": "2024-01-01T09:00:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/41",
            },
        ],
    }

    result = await list_workflow_runs(mock_client, "owner", "repo")

    assert "#42" in result
    assert "#41" in result
    assert "success" in result
    assert "in_progress" in result
    assert "2 of 2" in result


@pytest.mark.asyncio
async def test_list_workflow_runs_empty(mock_client):
    mock_client.list_workflow_runs.return_value = {"total_count": 0, "workflow_runs": []}

    result = await list_workflow_runs(mock_client, "owner", "repo")
    assert "No workflow runs" in result


# ── trigger_workflow ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_workflow(mock_client):
    mock_client.trigger_workflow.return_value = None

    result = await trigger_workflow(mock_client, "owner", "repo", "ci.yml", "main")

    mock_client.trigger_workflow.assert_called_once_with("owner", "repo", "ci.yml", "main", None)
    assert "ci.yml" in result
    assert "main" in result


@pytest.mark.asyncio
async def test_trigger_workflow_with_inputs(mock_client):
    mock_client.trigger_workflow.return_value = None

    result = await trigger_workflow(
        mock_client, "owner", "repo", "deploy.yml", "v1.0", inputs={"env": "prod"}
    )

    mock_client.trigger_workflow.assert_called_once_with(
        "owner", "repo", "deploy.yml", "v1.0", {"env": "prod"}
    )
    assert "prod" in result
