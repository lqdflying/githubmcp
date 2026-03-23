"""File operation tools: read_file, list_directory, find_files."""

import fnmatch

from src.cache import tree_cache
from src.github_client import GitHubClient, GitHubAPIError


async def _get_cached_tree(
    client: GitHubClient, owner: str, repo: str, ref: str | None
) -> list[dict]:
    """Get full repo tree, using cache when available."""
    cache_key = f"tree:{owner}/{repo}:{ref or 'default'}"
    cached = tree_cache.get(cache_key)
    if cached is not None:
        return cached

    tree = await client.get_full_tree(owner, repo, ref)
    tree_cache.set(cache_key, tree)
    return tree


async def read_file(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read file contents from a GitHub repository, optionally returning a specific line range.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository (e.g. "src/main.py").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        start_line: First line to return (1-based, inclusive). Omit to start from beginning.
        end_line: Last line to return (1-based, inclusive). Omit to read to end.

    Returns:
        The file contents as text (full or sliced to the requested line range).
    """
    content = await client.get_file_content(owner, repo, path, ref)

    # Apply line range if requested
    if start_line is not None or end_line is not None:
        lines = content.splitlines(keepends=True)
        total = len(lines)
        s = max(1, start_line or 1) - 1  # convert to 0-based
        e = min(total, end_line or total)
        header = f"Lines {s + 1}-{e} of {total} in {path}\n"
        return header + "".join(lines[s:e])

    return content


async def list_directory(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str = "",
    ref: str | None = None,
) -> str:
    """List contents of a directory in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: Directory path within the repository. Use "" or "/" for root.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.

    Returns:
        A listing of directory entries, one per line. Directories end with "/".
    """
    # Normalize path
    path = path.strip("/")

    data = await client.get_contents(owner, repo, path, ref)
    if not isinstance(data, list):
        raise GitHubAPIError(400, f"'{path}' is a file, not a directory.")

    lines = []
    for entry in sorted(data, key=lambda e: (e["type"] != "dir", e["name"])):
        name = entry["name"]
        if entry["type"] == "dir":
            lines.append(f"{name}/")
        else:
            size = entry.get("size", 0)
            lines.append(f"{name}  ({_human_size(size)})")

    return "\n".join(lines)


async def find_files(
    client: GitHubClient,
    owner: str,
    repo: str,
    pattern: str,
    ref: str | None = None,
) -> str:
    """Search for files matching a glob pattern in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        pattern: Glob pattern to match file paths (e.g. "**/*.py", "src/**/*.ts", "*.md").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.

    Returns:
        Matching file paths, one per line. Returns a message if no matches found.
    """
    tree = await _get_cached_tree(client, owner, repo, ref)

    # Filter to blob entries (files only) and match against the glob pattern
    matches = []
    for entry in tree:
        if entry["type"] != "blob":
            continue
        file_path = entry["path"]
        if fnmatch.fnmatch(file_path, pattern):
            matches.append(file_path)

    if not matches:
        return f"No files matching '{pattern}' found."

    matches.sort()
    header = f"Found {len(matches)} file(s) matching '{pattern}':\n"
    return header + "\n".join(matches)


def _human_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
