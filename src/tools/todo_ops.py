"""Todo tools: todo_write, todo_read, todo_update.

In-memory task list for tracking multi-step agent work within a session.
State is process-local (resets on server restart).
"""

_STATUS_ICON = {"pending": "○", "in_progress": "◉", "completed": "✓"}
_VALID_STATUSES = {"pending", "in_progress", "completed"}

# Module-level singleton — one list per server process
_todos: list[dict] = []


def todo_update(index: int, status: str) -> str:
    """Update the status of a single todo item by its index (0-based).

    Use this to check off a task as you complete it, without rewriting the
    whole list. Typical flow:
      1. Mark current task "in_progress"
      2. Do the work
      3. Mark it "completed"
      4. Mark next task "in_progress"
    """
    if not _todos:
        raise ValueError("Todo list is empty. Call todo_write first.")
    if index < 0 or index >= len(_todos):
        raise ValueError(f"Index {index} out of range (list has {len(_todos)} items).")
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
        )

    _todos[index]["status"] = status
    return _format_todos(_todos)


def todo_write(todos: list[dict]) -> str:
    """Replace the entire todo list.

    Each item must have:
      - "content": task description (str)
      - "status": "pending" | "in_progress" | "completed"

    Returns a formatted summary of the updated list.
    """
    global _todos

    # Validate
    for i, item in enumerate(todos):
        if "content" not in item:
            raise ValueError(f"Todo item {i} missing required field 'content'")
        status = item.get("status", "pending")
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Todo item {i} has invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
            )

    _todos = [{"content": t["content"], "status": t.get("status", "pending")} for t in todos]
    return _format_todos(_todos)


def todo_read() -> str:
    """Return the current todo list as formatted text."""
    if not _todos:
        return "Todo list is empty."
    return _format_todos(_todos)


def _format_todos(todos: list[dict]) -> str:
    total = len(todos)
    done = sum(1 for t in todos if t["status"] == "completed")
    lines = [f"Tasks ({done}/{total} completed):"]
    for t in todos:
        icon = _STATUS_ICON.get(t["status"], "?")
        lines.append(f"  {icon} {t['content']}  [{t['status']}]")
    return "\n".join(lines)
