"""Write operations: create branches, commit files, delete files."""

import base64
from typing import Any

from src.github_client import GitHubClient, GitHubAPIError


async def create_branch(
    client: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    from_ref: str | None = None,
) -> str:
    """Create a new branch from an existing ref (branch, tag, or commit SHA).

    If from_ref is not provided, the repo's default branch is used.
    """
    # Resolve from_ref to a commit SHA
    if from_ref:
        try:
            ref_data = await client.get_ref(owner, repo, from_ref)
            sha = ref_data["object"]["sha"]
        except GitHubAPIError:
            # Might be a bare commit SHA — validate via get_commit
            commit = await client.get_commit(owner, repo, from_ref)
            sha = commit["sha"]
    else:
        repo_data = await client.get_repo(owner, repo)
        default_branch = repo_data["default_branch"]
        ref_data = await client.get_ref(owner, repo, default_branch)
        sha = ref_data["object"]["sha"]

    await client.create_ref(owner, repo, f"refs/heads/{branch}", sha)
    return f"Created branch '{branch}' at commit {sha[:7]} (from {from_ref or 'default branch'})"


async def push_files(
    client: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    files: list[dict[str, str]],
    message: str,
) -> str:
    """Commit one or more files to a branch in a single commit.

    Each entry in `files` must have:
      - "path": file path in the repo (e.g. "src/main.py")
      - "content": UTF-8 text content

    Uses the Git Data API (blob → tree → commit → update ref) so multiple
    files land in one atomic commit.
    """
    if not files:
        raise ValueError("files list must not be empty")

    # Resolve branch to current commit + tree SHA
    ref_data = await client.get_ref(owner, repo, branch)
    parent_sha = ref_data["object"]["sha"]
    commit_data = await client.get_commit(owner, repo, parent_sha)
    base_tree_sha = commit_data["tree"]["sha"]

    # Create one blob per file
    tree_entries: list[dict[str, Any]] = []
    for f in files:
        blob = await client.create_blob(owner, repo, f["content"], encoding="utf-8")
        tree_entries.append(
            {"path": f["path"], "mode": "100644", "type": "blob", "sha": blob["sha"]}
        )

    # Create a new tree on top of the base tree
    new_tree = await client.create_tree(owner, repo, tree_entries, base_tree=base_tree_sha)

    # Create the commit
    new_commit = await client.create_commit_object(
        owner, repo, message, new_tree["sha"], [parent_sha]
    )
    new_sha = new_commit["sha"]

    # Advance the branch ref
    await client.update_ref(owner, repo, f"heads/{branch}", new_sha)

    file_list = "\n".join(f"  • {f['path']}" for f in files)
    return (
        f"Committed {len(files)} file(s) to '{branch}'\n"
        f"Commit: {new_sha[:7]}  {message}\n"
        f"Files:\n{file_list}"
    )


async def delete_file(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
    message: str,
    branch: str,
) -> str:
    """Delete a file from a branch.

    Fetches the current file SHA automatically before deleting.
    """
    # Need the current blob SHA for the Contents API delete call
    data = await client.get_contents(owner, repo, path, ref=branch)
    if isinstance(data, list):
        raise GitHubAPIError(400, f"'{path}' is a directory, not a file.")
    file_sha = data["sha"]

    await client.delete_contents(owner, repo, path, message, file_sha, branch)
    return f"Deleted '{path}' from branch '{branch}'\nCommit message: {message}"


async def list_workflow_runs(
    client: GitHubClient,
    owner: str,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    """List recent CI/CD workflow runs for a repository."""
    data = await client.list_workflow_runs(owner, repo, workflow_id, branch, status, per_page=limit)
    runs = data.get("workflow_runs", [])
    total = data.get("total_count", 0)

    if not runs:
        return "No workflow runs found."

    lines = [f"Workflow runs ({len(runs)} of {total} total):\n"]
    for run in runs:
        status_icon = {
            "completed": {"success": "✓", "failure": "✗", "cancelled": "⊘"}.get(
                run.get("conclusion", ""), "?"
            ),
            "in_progress": "⟳",
            "queued": "…",
            "waiting": "⏳",
        }.get(run.get("status", ""), "?")

        lines.append(
            f"{status_icon} #{run['run_number']}  {run['name']}\n"
            f"   Branch: {run.get('head_branch', 'N/A')}  "
            f"Status: {run.get('status')}  "
            f"Conclusion: {run.get('conclusion', 'N/A')}\n"
            f"   Started: {run.get('run_started_at', 'N/A')}\n"
            f"   URL: {run.get('html_url', '')}\n"
        )

    return "\n".join(lines)


async def trigger_workflow(
    client: GitHubClient,
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: dict[str, str] | None = None,
) -> str:
    """Trigger a workflow_dispatch event to run a CI workflow."""
    await client.trigger_workflow(owner, repo, workflow_id, ref, inputs)
    inputs_str = f"\nInputs: {inputs}" if inputs else ""
    return f"Triggered workflow '{workflow_id}' on ref '{ref}'{inputs_str}"
