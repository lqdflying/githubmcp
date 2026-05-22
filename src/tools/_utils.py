"""Shared utility functions used across tool modules."""

from src.cache import tree_cache
from src.github_client import GitHubClient


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


def _human_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
