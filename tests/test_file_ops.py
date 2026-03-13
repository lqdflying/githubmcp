"""Tests for file operation tools."""

import pytest
from src.tools.file_ops import read_file, list_directory, find_files
from src.github_client import GitHubAPIError


@pytest.mark.asyncio
async def test_read_file_full(mock_client):
    mock_client.get_file_content.return_value = "line1\nline2\nline3\nline4\nline5\n"

    result = await read_file(mock_client, "owner", "repo", "test.py")
    assert "line1" in result
    assert "line5" in result
    mock_client.get_file_content.assert_called_once_with("owner", "repo", "test.py", None)


@pytest.mark.asyncio
async def test_read_file_line_range(mock_client):
    mock_client.get_file_content.return_value = "line1\nline2\nline3\nline4\nline5\n"

    result = await read_file(mock_client, "owner", "repo", "test.py", start_line=2, end_line=4)
    assert "Lines 2-4 of 5" in result
    assert "line2" in result
    assert "line4" in result
    assert "line1" not in result
    assert "line5" not in result


@pytest.mark.asyncio
async def test_read_file_with_ref(mock_client):
    mock_client.get_file_content.return_value = "content"

    await read_file(mock_client, "owner", "repo", "test.py", ref="develop")
    mock_client.get_file_content.assert_called_once_with("owner", "repo", "test.py", "develop")


@pytest.mark.asyncio
async def test_read_file_not_found(mock_client):
    mock_client.get_file_content.side_effect = GitHubAPIError(404, "Resource not found.")

    with pytest.raises(GitHubAPIError):
        await read_file(mock_client, "owner", "repo", "nonexistent.py")


@pytest.mark.asyncio
async def test_list_directory(mock_client):
    mock_client.get_contents.return_value = [
        {"name": "src", "type": "dir", "size": 0},
        {"name": "README.md", "type": "file", "size": 500},
        {"name": "setup.py", "type": "file", "size": 200},
    ]

    result = await list_directory(mock_client, "owner", "repo", "")
    # Directories should come first
    lines = result.strip().split("\n")
    assert lines[0] == "src/"
    assert "README.md" in result
    assert "setup.py" in result


@pytest.mark.asyncio
async def test_list_directory_file_path(mock_client):
    mock_client.get_contents.return_value = {"name": "test.py", "type": "file"}

    with pytest.raises(GitHubAPIError, match="not a directory"):
        await list_directory(mock_client, "owner", "repo", "test.py")


@pytest.mark.asyncio
async def test_find_files_python(mock_client, sample_tree):
    mock_client.get_full_tree.return_value = sample_tree

    result = await find_files(mock_client, "owner", "repo", "**/*.py")
    assert "src/main.py" in result
    assert "src/utils.py" in result
    assert "tests/test_main.py" in result
    assert "README.md" not in result


@pytest.mark.asyncio
async def test_find_files_markdown(mock_client, sample_tree):
    mock_client.get_full_tree.return_value = sample_tree

    result = await find_files(mock_client, "owner", "repo", "*.md")
    assert "README.md" in result


@pytest.mark.asyncio
async def test_find_files_no_matches(mock_client, sample_tree):
    mock_client.get_full_tree.return_value = sample_tree

    result = await find_files(mock_client, "owner", "repo", "**/*.rs")
    assert "No files matching" in result
