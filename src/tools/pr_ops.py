"""Pull request and issue operations."""

from src.github_client import GitHubClient


async def create_pull_request(
    client: GitHubClient,
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
) -> str:
    """Open a new pull request."""
    pr = await client.create_pull_request(owner, repo, title, head, base, body, draft)
    status = "draft" if pr.get("draft") else "open"
    return (
        f"Created PR #{pr['number']}: {pr['title']}\n"
        f"Status: {status}\n"
        f"From '{head}' → '{base}'\n"
        f"URL: {pr['html_url']}"
    )


async def list_pull_requests(
    client: GitHubClient,
    owner: str,
    repo: str,
    state: str = "open",
    head: str | None = None,
    base: str | None = None,
    limit: int = 20,
) -> str:
    """List pull requests with optional filters."""
    prs = await client.list_pull_requests(owner, repo, state, head, base, per_page=limit)

    if not prs:
        return f"No {state} pull requests found."

    lines = [f"Pull Requests ({state}) — {len(prs)} results:\n"]
    for pr in prs:
        draft_tag = " [DRAFT]" if pr.get("draft") else ""
        lines.append(
            f"#{pr['number']}{draft_tag}  {pr['title']}\n"
            f"  {pr['head']['label']} → {pr['base']['label']}\n"
            f"  By: {pr['user']['login']}  Updated: {pr['updated_at'][:10]}\n"
            f"  {pr['html_url']}\n"
        )
    return "\n".join(lines)


async def get_pull_request(
    client: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
) -> str:
    """Get details of a specific pull request."""
    pr = await client.get_pull_request(owner, repo, pull_number)
    mergeable = pr.get("mergeable")
    mergeable_str = {True: "yes", False: "no (conflicts)", None: "unknown"}.get(
        mergeable, str(mergeable)
    )
    return (
        f"PR #{pr['number']}: {pr['title']}\n"
        f"State: {pr['state']}{'  [DRAFT]' if pr.get('draft') else ''}\n"
        f"From '{pr['head']['label']}' → '{pr['base']['label']}'\n"
        f"By: {pr['user']['login']}  Created: {pr['created_at'][:10]}\n"
        f"Mergeable: {mergeable_str}\n"
        f"Commits: {pr.get('commits', 'N/A')}  "
        f"Changed files: {pr.get('changed_files', 'N/A')}  "
        f"+{pr.get('additions', 0)} -{pr.get('deletions', 0)}\n"
        f"URL: {pr['html_url']}\n"
        f"\n{pr.get('body') or '(no description)'}"
    )


async def merge_pull_request(
    client: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
    commit_title: str | None = None,
    merge_method: str = "merge",
) -> str:
    """Merge a pull request."""
    result = await client.merge_pull_request(owner, repo, pull_number, commit_title, merge_method)
    sha = result.get("sha", "")
    return (
        f"Merged PR #{pull_number}  ({merge_method})\n"
        f"Commit: {sha[:7] if sha else 'N/A'}\n"
        f"Message: {result.get('message', '')}"
    )


async def add_pr_comment(
    client: GitHubClient,
    owner: str,
    repo: str,
    pull_number: int,
    body: str,
) -> str:
    """Add a comment to a pull request (uses the issue comments endpoint)."""
    comment = await client.create_issue_comment(owner, repo, pull_number, body)
    return (
        f"Added comment to PR #{pull_number}\n"
        f"Comment ID: {comment.get('id')}\n"
        f"URL: {comment.get('html_url', '')}"
    )


async def create_issue(
    client: GitHubClient,
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
) -> str:
    """Create a new issue in a repository."""
    issue = await client.create_issue(owner, repo, title, body, labels)
    label_str = ""
    if issue.get("labels"):
        label_str = f"\nLabels: {', '.join(lb['name'] for lb in issue['labels'])}"
    return (
        f"Created issue #{issue['number']}: {issue['title']}{label_str}\nURL: {issue['html_url']}"
    )
