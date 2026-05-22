"""Code search tools: search_code, get_file_summary."""

import fnmatch
import re

from src.github_client import GitHubClient, GitHubAPIError
from src.tools._utils import _get_cached_tree, _human_size


# Map file extensions to language names
_EXT_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".xml": "XML",
    ".md": "Markdown",
    ".toml": "TOML",
    ".ini": "INI",
    ".tf": "Terraform",
    ".bicep": "Bicep",
    ".r": "R",
    ".lua": "Lua",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
}


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    for ext, lang in _EXT_LANGUAGES.items():
        if path.endswith(ext):
            return lang
    return "Unknown"


async def search_code(
    client: GitHubClient,
    owner: str,
    repo: str,
    query: str,
    is_regexp: bool = False,
    include_pattern: str | None = None,
    ref: str | None = None,
    max_results: int = 50,
) -> str:
    """Search for text or regex patterns across files in a GitHub repository.

    For simple text queries on the default branch, uses GitHub's Search API.
    For regex patterns or specific branches, fetches files and searches locally.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        query: Search string or regex pattern.
        is_regexp: If True, treat query as a Python regex pattern.
        include_pattern: Optional glob pattern to limit search to matching files (e.g. "*.py").
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        max_results: Maximum number of matching lines to return.

    Returns:
        Search results showing file path, line number, and matching line content.
    """
    # For regex or non-default-branch searches, do local search
    if is_regexp or ref:
        return await _local_search(
            client, owner, repo, query, is_regexp, include_pattern, ref, max_results
        )

    # Use GitHub Search API for simple text on default branch
    try:
        search_query = query
        if include_pattern:
            # Extract extension from glob for GitHub search filtering
            ext = _extract_extension(include_pattern)
            if ext:
                search_query += f" extension:{ext}"

        result = await client.search_code(search_query, owner, repo, per_page=min(max_results, 100))
        items = result.get("items", [])
        if not items:
            return f"No results found for '{query}'."

        lines = [f"Found {result.get('total_count', len(items))} result(s) for '{query}':\n"]
        for item in items[:max_results]:
            path = item.get("path", "")
            if include_pattern and not fnmatch.fnmatch(path, include_pattern):
                continue
            lines.append(f"  {path}")

        return "\n".join(lines)

    except GitHubAPIError:
        # Fall back to local search if GitHub Search API fails
        return await _local_search(
            client, owner, repo, query, is_regexp, include_pattern, ref, max_results
        )


async def _local_search(
    client: GitHubClient,
    owner: str,
    repo: str,
    query: str,
    is_regexp: bool,
    include_pattern: str | None,
    ref: str | None,
    max_results: int,
) -> str:
    """Fetch files from the repo tree and search contents locally."""
    tree = await _get_cached_tree(client, owner, repo, ref)

    # Build list of files to search
    files_to_search = []
    for entry in tree:
        if entry["type"] != "blob":
            continue
        path = entry["path"]
        # Skip binary-looking files
        if _is_likely_binary(path):
            continue
        if include_pattern and not fnmatch.fnmatch(path, include_pattern):
            continue
        # Skip very large files (> 500KB)
        if entry.get("size", 0) > 500_000:
            continue
        files_to_search.append(path)

    if is_regexp:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            return f"Invalid regex pattern: {e}"
    else:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    results = []
    for file_path in files_to_search:
        if len(results) >= max_results:
            break
        try:
            content = await client.get_file_content(owner, repo, file_path, ref)
        except GitHubAPIError:
            continue

        for i, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                results.append(f"  {file_path}:{i}: {line.strip()}")
                if len(results) >= max_results:
                    break

    if not results:
        return f"No results found for '{query}'."

    header = f"Found {len(results)} match(es) for '{query}':\n"
    return header + "\n".join(results)


async def get_file_summary(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    preview_lines: int = 20,
) -> str:
    """Get an overview of a file including size, line count, language, and a content preview.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        preview_lines: Number of lines to show as preview (default: 20).

    Returns:
        A formatted summary of the file with metadata and first N lines.
    """
    content = await client.get_file_content(owner, repo, path, ref)
    lines = content.splitlines()
    language = _detect_language(path)
    size_bytes = len(content.encode("utf-8"))

    parts = [
        f"File: {path}",
        f"Language: {language}",
        f"Size: {_human_size(size_bytes)}",
        f"Lines: {len(lines)}",
        "",
        f"--- Preview (first {min(preview_lines, len(lines))} lines) ---",
    ]
    parts.extend(lines[:preview_lines])

    if len(lines) > preview_lines:
        parts.append(f"\n... ({len(lines) - preview_lines} more lines)")

    return "\n".join(parts)


def _extract_extension(glob_pattern: str) -> str | None:
    """Try to extract a file extension from a glob pattern."""
    if "." in glob_pattern:
        ext = glob_pattern.rsplit(".", 1)[-1]
        if ext.isalpha():
            return ext
    return None


_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".zip",
    ".gz",
    ".tar",
    ".rar",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".pyc",
    ".class",
    ".jar",
    ".lock",
}


def _is_likely_binary(path: str) -> bool:
    """Check if a file path looks like a binary file."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _BINARY_EXTENSIONS)
