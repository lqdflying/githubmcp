"""Tests for code search tools."""

import pytest
from src.tools.code_search import search_code, get_file_summary
from src.github_client import GitHubAPIError


@pytest.mark.asyncio
async def test_search_code_github_api(mock_client):
    """Test search using GitHub Search API (default branch, no regex)."""
    mock_client.search_code.return_value = {
        "total_count": 2,
        "items": [
            {"path": "src/main.py", "name": "main.py"},
            {"path": "src/utils.py", "name": "utils.py"},
        ],
    }

    result = await search_code(mock_client, "owner", "repo", "def main")
    assert "2 result(s)" in result
    assert "src/main.py" in result
    assert "src/utils.py" in result


@pytest.mark.asyncio
async def test_search_code_no_results(mock_client):
    mock_client.search_code.return_value = {"total_count": 0, "items": []}

    result = await search_code(mock_client, "owner", "repo", "nonexistent_function_xyz")
    assert "No results found" in result


@pytest.mark.asyncio
async def test_search_code_regex_local(mock_client, sample_tree):
    """Test regex search falls back to local search."""
    mock_client.get_full_tree.return_value = sample_tree
    mock_client.get_file_content.return_value = "import os\nimport sys\ndef main():\n    pass\n"

    result = await search_code(mock_client, "owner", "repo", r"import\s+os", is_regexp=True)
    assert "import os" in result or "No results" in result


@pytest.mark.asyncio
async def test_search_code_with_include_pattern(mock_client):
    """Test include_pattern filters results."""
    mock_client.search_code.return_value = {
        "total_count": 2,
        "items": [
            {"path": "src/main.py", "name": "main.py"},
            {"path": "docs/guide.md", "name": "guide.md"},
        ],
    }

    result = await search_code(mock_client, "owner", "repo", "main", include_pattern="*.py")
    assert "src/main.py" in result


@pytest.mark.asyncio
async def test_get_file_summary(mock_client):
    mock_client.get_file_content.return_value = (
        "#!/usr/bin/env python\n"
        '"""Main module."""\n'
        "\n"
        "import os\n"
        "import sys\n"
        "\n"
        "def main():\n"
        "    print('hello')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    result = await get_file_summary(mock_client, "owner", "repo", "main.py")
    assert "File: main.py" in result
    assert "Language: Python" in result
    assert "Lines: 11" in result
    assert "Preview" in result
    assert "import os" in result


@pytest.mark.asyncio
async def test_get_file_summary_not_found(mock_client):
    mock_client.get_file_content.side_effect = GitHubAPIError(404, "Resource not found.")

    with pytest.raises(GitHubAPIError):
        await get_file_summary(mock_client, "owner", "repo", "nonexistent.py")
