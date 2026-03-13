"""Repository info tools: get_repo_info, get_repo_structure, get_languages."""

import fnmatch

from src.cache import tree_cache
from src.github_client import GitHubClient


async def _get_cached_tree(client: GitHubClient, owner: str, repo: str, ref: str | None) -> list[dict]:
    cache_key = f"tree:{owner}/{repo}:{ref or 'default'}"
    cached = tree_cache.get(cache_key)
    if cached is not None:
        return cached
    tree = await client.get_full_tree(owner, repo, ref)
    tree_cache.set(cache_key, tree)
    return tree


async def get_repo_info(
    client: GitHubClient,
    owner: str,
    repo: str,
) -> str:
    """Get metadata and overview information about a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.

    Returns:
        Repository information including description, default branch, language, size, visibility, and dates.
    """
    data = await client.get_repo(owner, repo)

    visibility = "Private" if data.get("private") else "Public"
    size_kb = data.get("size", 0)
    size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb} KB"

    lines = [
        f"Repository: {data.get('full_name', f'{owner}/{repo}')}",
        f"Description: {data.get('description') or '(none)'}",
        f"Visibility: {visibility}",
        f"Default branch: {data.get('default_branch', 'main')}",
        f"Primary language: {data.get('language') or '(none)'}",
        f"Size: {size_str}",
        f"Stars: {data.get('stargazers_count', 0)}",
        f"Forks: {data.get('forks_count', 0)}",
        f"Open issues: {data.get('open_issues_count', 0)}",
        f"Created: {(data.get('created_at') or '')[:10]}",
        f"Last updated: {(data.get('updated_at') or '')[:10]}",
        f"Last pushed: {(data.get('pushed_at') or '')[:10]}",
    ]

    topics = data.get("topics", [])
    if topics:
        lines.append(f"Topics: {', '.join(topics)}")

    license_info = data.get("license")
    if license_info:
        lines.append(f"License: {license_info.get('spdx_id', 'Unknown')}")

    return "\n".join(lines)


async def get_repo_structure(
    client: GitHubClient,
    owner: str,
    repo: str,
    ref: str | None = None,
    max_depth: int | None = None,
    path_filter: str | None = None,
) -> str:
    """Get the file/folder tree structure of a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        max_depth: Maximum depth of tree to display (e.g. 2 for top-level + one level).
        path_filter: Optional glob pattern to filter paths (e.g. "src/**").

    Returns:
        An indented tree view of the repository structure.
    """
    tree = await _get_cached_tree(client, owner, repo, ref)

    # Build sorted list of paths
    entries = []
    for entry in tree:
        path = entry["path"]
        entry_type = entry["type"]

        if path_filter and not fnmatch.fnmatch(path, path_filter):
            continue

        depth = path.count("/") + 1
        if max_depth and depth > max_depth:
            continue

        entries.append((path, entry_type))

    entries.sort(key=lambda e: e[0])

    if not entries:
        return "No entries found."

    lines = [f"Structure of {owner}/{repo}:\n"]
    for path, entry_type in entries:
        depth = path.count("/")
        indent = "  " * depth
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        suffix = "/" if entry_type == "tree" else ""
        lines.append(f"{indent}{name}{suffix}")

    lines.append(f"\nTotal: {len(entries)} entries")
    return "\n".join(lines)


async def get_languages(
    client: GitHubClient,
    owner: str,
    repo: str,
) -> str:
    """Get the programming language breakdown of a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.

    Returns:
        Language breakdown showing each language and its percentage of the codebase.
    """
    data = await client.get_languages(owner, repo)

    if not data:
        return f"No language data available for {owner}/{repo}."

    total_bytes = sum(data.values())
    lines = [f"Languages in {owner}/{repo}:\n"]

    for lang, byte_count in sorted(data.items(), key=lambda x: x[1], reverse=True):
        pct = (byte_count / total_bytes) * 100 if total_bytes > 0 else 0
        lines.append(f"  {lang:20s}  {pct:5.1f}%  ({_human_size(byte_count)})")

    lines.append(f"\nTotal: {_human_size(total_bytes)}")
    return "\n".join(lines)


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
