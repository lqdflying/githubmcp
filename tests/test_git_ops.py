"""Tests for git operation tools."""

import pytest
from src.tools.git_ops import list_branches, get_commits, get_diff, get_blame, get_file_history


@pytest.mark.asyncio
async def test_list_branches(mock_client):
    mock_client.get_repo.return_value = {"default_branch": "main"}
    mock_client.list_branches.return_value = [
        {"name": "main", "commit": {"sha": "abc1234567890"}},
        {"name": "develop", "commit": {"sha": "def4567890123"}},
        {"name": "feature/new-ui", "commit": {"sha": "789abc0123456"}},
    ]

    result = await list_branches(mock_client, "owner", "repo")
    assert "main *" in result
    assert "develop" in result
    assert "feature/new-ui" in result
    assert "abc1234" in result


@pytest.mark.asyncio
async def test_get_commits(mock_client):
    mock_client.list_commits.return_value = [
        {
            "sha": "abc1234567890",
            "commit": {
                "author": {"name": "Alice", "date": "2025-01-15T10:30:00Z"},
                "message": "Add new feature\n\nDetailed description here.",
            },
        },
        {
            "sha": "def4567890123",
            "commit": {
                "author": {"name": "Bob", "date": "2025-01-14T09:00:00Z"},
                "message": "Fix bug #42",
            },
        },
    ]

    result = await get_commits(mock_client, "owner", "repo")
    assert "abc1234" in result
    assert "Alice" in result
    assert "Add new feature" in result
    assert "Bob" in result
    assert "Fix bug #42" in result


@pytest.mark.asyncio
async def test_get_commits_with_path(mock_client):
    mock_client.list_commits.return_value = [
        {
            "sha": "abc1234567890",
            "commit": {
                "author": {"name": "Alice", "date": "2025-01-15T10:30:00Z"},
                "message": "Update main.py",
            },
        },
    ]

    result = await get_commits(mock_client, "owner", "repo", path="src/main.py")
    assert "src/main.py" in result
    assert "Update main.py" in result


@pytest.mark.asyncio
async def test_get_commits_empty(mock_client):
    mock_client.list_commits.return_value = []

    result = await get_commits(mock_client, "owner", "repo")
    assert "No commits found" in result


@pytest.mark.asyncio
async def test_get_diff(mock_client):
    mock_client.compare.return_value = {
        "status": "ahead",
        "ahead_by": 3,
        "behind_by": 0,
        "total_commits": 3,
        "files": [
            {
                "filename": "src/main.py",
                "status": "modified",
                "additions": 10,
                "deletions": 2,
                "patch": "@@ -1,5 +1,13 @@\n+import os\n def main():\n-    pass\n+    print('hello')",
            },
            {
                "filename": "tests/test_new.py",
                "status": "added",
                "additions": 20,
                "deletions": 0,
                "patch": "@@ -0,0 +1,20 @@\n+import pytest",
            },
        ],
    }

    result = await get_diff(mock_client, "owner", "repo", "main", "feature")
    assert "main...feature" in result
    assert "Commits: 3" in result
    assert "src/main.py" in result
    assert "modified" in result
    assert "+10 -2" in result
    assert "tests/test_new.py" in result
    assert "added" in result


@pytest.mark.asyncio
async def test_get_blame(mock_client):
    mock_client.get_blame.return_value = [
        {
            "startingLine": 1,
            "endingLine": 5,
            "commit": {
                "oid": "abc1234567890",
                "message": "Initial commit",
                "author": {"name": "Alice", "email": "alice@example.com", "date": "2025-01-10"},
            },
        },
        {
            "startingLine": 6,
            "endingLine": 10,
            "commit": {
                "oid": "def4567890123",
                "message": "Add error handling",
                "author": {"name": "Bob", "email": "bob@example.com", "date": "2025-01-15"},
            },
        },
    ]

    result = await get_blame(mock_client, "owner", "repo", "src/main.py")
    assert "L1-L5" in result
    assert "abc1234" in result
    assert "Alice" in result
    assert "Initial commit" in result
    assert "L6-L10" in result
    assert "Bob" in result


@pytest.mark.asyncio
async def test_get_file_history(mock_client):
    mock_client.list_commits.return_value = [
        {
            "sha": "abc1234567890",
            "commit": {
                "author": {"name": "Alice", "date": "2025-01-15T10:30:00Z"},
                "message": "Refactor main.py",
            },
        },
    ]

    result = await get_file_history(mock_client, "owner", "repo", "src/main.py")
    assert "src/main.py" in result
    assert "Refactor main.py" in result
