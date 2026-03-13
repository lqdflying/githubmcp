"""Tests for repository info tools."""

import pytest
from src.tools.repo_info import get_repo_info, get_repo_structure, get_languages


@pytest.mark.asyncio
async def test_get_repo_info(mock_client):
    mock_client.get_repo.return_value = {
        "full_name": "owner/repo",
        "description": "A test repository",
        "private": False,
        "default_branch": "main",
        "language": "Python",
        "size": 2048,
        "stargazers_count": 100,
        "forks_count": 25,
        "open_issues_count": 5,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-15T10:30:00Z",
        "pushed_at": "2025-01-15T10:30:00Z",
        "topics": ["python", "mcp", "github"],
        "license": {"spdx_id": "MIT"},
    }

    result = await get_repo_info(mock_client, "owner", "repo")
    assert "owner/repo" in result
    assert "A test repository" in result
    assert "Public" in result
    assert "Python" in result
    assert "Stars: 100" in result
    assert "MIT" in result
    assert "python, mcp, github" in result


@pytest.mark.asyncio
async def test_get_repo_info_private(mock_client):
    mock_client.get_repo.return_value = {
        "full_name": "owner/private-repo",
        "description": None,
        "private": True,
        "default_branch": "main",
        "language": None,
        "size": 100,
        "stargazers_count": 0,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2024-06-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "pushed_at": "2025-01-01T00:00:00Z",
    }

    result = await get_repo_info(mock_client, "owner", "private-repo")
    assert "Private" in result
    assert "(none)" in result  # No description/language


@pytest.mark.asyncio
async def test_get_repo_structure(mock_client, sample_tree):
    mock_client.get_full_tree.return_value = sample_tree

    result = await get_repo_structure(mock_client, "owner", "repo")
    assert "Structure of owner/repo" in result
    assert "README.md" in result
    assert "src/" in result
    assert "main.py" in result
    assert "Total:" in result


@pytest.mark.asyncio
async def test_get_repo_structure_max_depth(mock_client, sample_tree):
    mock_client.get_full_tree.return_value = sample_tree

    result = await get_repo_structure(mock_client, "owner", "repo", max_depth=1)
    assert "README.md" in result
    assert "src/" in result
    # Depth 2+ items should not appear
    assert "main.py" not in result


@pytest.mark.asyncio
async def test_get_languages(mock_client):
    mock_client.get_languages.return_value = {
        "Python": 50000,
        "JavaScript": 30000,
        "HTML": 10000,
        "CSS": 5000,
    }

    result = await get_languages(mock_client, "owner", "repo")
    assert "Python" in result
    assert "JavaScript" in result
    assert "52.6%" in result  # Python percentage
    assert "Total:" in result


@pytest.mark.asyncio
async def test_get_languages_empty(mock_client):
    mock_client.get_languages.return_value = {}

    result = await get_languages(mock_client, "owner", "repo")
    assert "No language data" in result
