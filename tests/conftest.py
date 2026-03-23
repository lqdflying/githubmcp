"""Shared test fixtures for mocking the GitHub API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.github_client import GitHubClient, RateLimitInfo


@pytest.fixture
def mock_client():
    """Create a mocked GitHubClient with all methods as AsyncMocks."""
    client = MagicMock(spec=GitHubClient)
    client.rate_limit = RateLimitInfo(remaining=4999, limit=5000, reset_at=1700000000)

    # REST methods
    client.get_repo = AsyncMock()
    client.get_languages = AsyncMock()
    client.get_contents = AsyncMock()
    client.get_tree = AsyncMock()
    client.get_blob = AsyncMock()
    client.get_ref = AsyncMock()
    client.get_commit = AsyncMock()
    client.list_branches = AsyncMock()
    client.list_commits = AsyncMock()
    client.compare = AsyncMock()
    client.search_code = AsyncMock()
    client.get_blame = AsyncMock()
    client.validate_token = AsyncMock()
    client.get_file_content = AsyncMock()
    client.get_full_tree = AsyncMock()
    client.close = AsyncMock()
    client.graphql = AsyncMock()

    # Write: Git Data API
    client.create_ref = AsyncMock()
    client.update_ref = AsyncMock()
    client.create_blob = AsyncMock()
    client.create_tree = AsyncMock()
    client.create_commit_object = AsyncMock()

    # Write: Contents API
    client.create_or_update_contents = AsyncMock()
    client.delete_contents = AsyncMock()

    # Pull Requests
    client.list_pull_requests = AsyncMock()
    client.get_pull_request = AsyncMock()
    client.create_pull_request = AsyncMock()
    client.merge_pull_request = AsyncMock()

    # Issues & Comments
    client.create_issue = AsyncMock()
    client.create_issue_comment = AsyncMock()

    # Actions / Workflows
    client.list_workflow_runs = AsyncMock()
    client.trigger_workflow = AsyncMock()
    client.get_workflow_run_jobs = AsyncMock()
    client.download_workflow_run_logs = AsyncMock()

    return client


@pytest.fixture
def sample_tree():
    """A sample repo tree for testing."""
    return [
        {"path": "README.md", "type": "blob", "size": 500},
        {"path": "setup.py", "type": "blob", "size": 200},
        {"path": "pyproject.toml", "type": "blob", "size": 300},
        {"path": "src", "type": "tree", "size": 0},
        {"path": "src/__init__.py", "type": "blob", "size": 0},
        {"path": "src/main.py", "type": "blob", "size": 1500},
        {"path": "src/utils.py", "type": "blob", "size": 800},
        {"path": "src/models", "type": "tree", "size": 0},
        {"path": "src/models/__init__.py", "type": "blob", "size": 0},
        {"path": "src/models/user.py", "type": "blob", "size": 600},
        {"path": "tests", "type": "tree", "size": 0},
        {"path": "tests/__init__.py", "type": "blob", "size": 0},
        {"path": "tests/test_main.py", "type": "blob", "size": 900},
        {"path": "docs/guide.md", "type": "blob", "size": 2000},
        {"path": "assets/logo.png", "type": "blob", "size": 50000},
    ]
