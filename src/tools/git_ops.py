"""Git operation tools: list_branches, get_commits, get_diff, get_blame, get_file_history."""

from src.github_client import GitHubClient


async def list_branches(
    client: GitHubClient,
    owner: str,
    repo: str,
) -> str:
    """List all branches in a GitHub repository.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.

    Returns:
        A list of branch names. The default branch is marked with an asterisk (*).
    """
    repo_data = await client.get_repo(owner, repo)
    default_branch = repo_data.get("default_branch", "main")

    branches = await client.list_branches(owner, repo)
    lines = []
    for branch in branches:
        name = branch["name"]
        marker = " *" if name == default_branch else ""
        sha = branch["commit"]["sha"][:7]
        lines.append(f"  {name}{marker}  ({sha})")

    header = f"Branches in {owner}/{repo} (* = default):\n"
    return header + "\n".join(lines)


async def get_commits(
    client: GitHubClient,
    owner: str,
    repo: str,
    ref: str | None = None,
    path: str | None = None,
    limit: int = 20,
) -> str:
    """Get commit history for a repository or specific file.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        ref: Branch, tag, or commit SHA to start from. Defaults to the repo's default branch.
        path: Optional file path to filter commits that touched this file.
        limit: Maximum number of commits to return (default: 20).

    Returns:
        Formatted commit history with SHA, author, date, and message.
    """
    commits = await client.list_commits(owner, repo, sha=ref, path=path, per_page=limit)

    if not commits:
        msg = "No commits found"
        if path:
            msg += f" for '{path}'"
        return msg + "."

    lines = []
    context = f" for '{path}'" if path else ""
    lines.append(f"Commit history{context} in {owner}/{repo}:\n")

    for commit_data in commits:
        sha = commit_data["sha"][:7]
        commit = commit_data.get("commit", {})
        author_info = commit.get("author", {})
        author = author_info.get("name", "Unknown")
        date = author_info.get("date", "")[:10]  # YYYY-MM-DD
        message = commit.get("message", "").split("\n")[0]  # First line only
        lines.append(f"  {sha}  {date}  {author}")
        lines.append(f"         {message}")

    return "\n".join(lines)


async def get_diff(
    client: GitHubClient,
    owner: str,
    repo: str,
    base: str,
    head: str,
) -> str:
    """Compare two branches, tags, or commits and show the diff.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        base: Base ref (branch, tag, or commit SHA) for comparison.
        head: Head ref (branch, tag, or commit SHA) for comparison.

    Returns:
        A summary of changes between base and head, including file-level diffs.
    """
    comparison = await client.compare(owner, repo, base, head)

    status = comparison.get("status", "unknown")
    ahead = comparison.get("ahead_by", 0)
    behind = comparison.get("behind_by", 0)
    total_commits = comparison.get("total_commits", 0)
    files = comparison.get("files", [])

    lines = [
        f"Comparing {base}...{head} in {owner}/{repo}:",
        f"  Status: {status} | Commits: {total_commits} | Ahead: {ahead} | Behind: {behind}",
        f"  Files changed: {len(files)}",
        "",
    ]

    for f in files:
        filename = f.get("filename", "")
        file_status = f.get("status", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        lines.append(f"  {file_status:10s}  +{additions} -{deletions}  {filename}")

        # Include patch content (truncated if very long)
        patch = f.get("patch", "")
        if patch:
            patch_lines = patch.splitlines()
            if len(patch_lines) > 50:
                lines.extend(f"    {pl}" for pl in patch_lines[:50])
                lines.append(f"    ... ({len(patch_lines) - 50} more lines)")
            else:
                lines.extend(f"    {pl}" for pl in patch_lines)
        lines.append("")

    return "\n".join(lines)


async def get_blame(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    ref: str = "HEAD",
) -> str:
    """Get blame information for a file, showing which commit last modified each line.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to HEAD.

    Returns:
        Blame ranges showing line ranges, commit SHA, author, date, and commit message.
    """
    ranges = await client.get_blame(owner, repo, path, ref)

    lines = [f"Blame for {path} at {ref}:\n"]
    for r in ranges:
        start = r["startingLine"]
        end = r["endingLine"]
        commit = r["commit"]
        sha = commit["oid"][:7]
        author_info = commit.get("author", {})
        author = author_info.get("name", "Unknown")
        date = (author_info.get("date", "") or "")[:10]
        message = commit.get("message", "").split("\n")[0]

        line_range = f"L{start}-L{end}" if start != end else f"L{start}"
        lines.append(f"  {line_range:12s}  {sha}  {date}  {author}")
        lines.append(f"  {'':12s}  {message}")

    return "\n".join(lines)


async def get_file_history(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    limit: int = 20,
) -> str:
    """Get the commit history for a specific file.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA. Defaults to the repo's default branch.
        limit: Maximum number of commits to return (default: 20).

    Returns:
        Formatted list of commits that modified this file.
    """
    return await get_commits(client, owner, repo, ref=ref, path=path, limit=limit)
