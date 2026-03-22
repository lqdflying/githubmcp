"""Tests for todo_ops: todo_write and todo_read."""

import pytest
from src.tools import todo_ops


@pytest.fixture(autouse=True)
def reset_todos():
    """Reset the global todo list before each test."""
    todo_ops._todos = []
    yield
    todo_ops._todos = []


def test_todo_write_basic():
    result = todo_ops.todo_write([
        {"content": "Step one", "status": "completed"},
        {"content": "Step two", "status": "in_progress"},
        {"content": "Step three", "status": "pending"},
    ])
    assert "1/3 completed" in result
    assert "Step one" in result
    assert "Step two" in result
    assert "Step three" in result


def test_todo_write_replaces_list():
    todo_ops.todo_write([{"content": "Old task", "status": "pending"}])
    todo_ops.todo_write([{"content": "New task", "status": "in_progress"}])
    result = todo_ops.todo_read()
    assert "Old task" not in result
    assert "New task" in result


def test_todo_write_default_status():
    result = todo_ops.todo_write([{"content": "No status given"}])
    assert "pending" in result


def test_todo_read_empty():
    result = todo_ops.todo_read()
    assert result == "Todo list is empty."


def test_todo_read_after_write():
    todo_ops.todo_write([
        {"content": "Do something", "status": "completed"},
        {"content": "Do another", "status": "pending"},
    ])
    result = todo_ops.todo_read()
    assert "1/2 completed" in result
    assert "Do something" in result
    assert "Do another" in result


def test_todo_write_invalid_status():
    with pytest.raises(ValueError, match="invalid status"):
        todo_ops.todo_write([{"content": "Bad item", "status": "unknown"}])


def test_todo_write_missing_content():
    with pytest.raises(ValueError, match="missing required field 'content'"):
        todo_ops.todo_write([{"status": "pending"}])


def test_todo_write_empty_list():
    todo_ops.todo_write([{"content": "something", "status": "pending"}])
    todo_ops.todo_write([])
    result = todo_ops.todo_read()
    assert result == "Todo list is empty."
