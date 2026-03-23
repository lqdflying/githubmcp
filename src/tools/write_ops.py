"""Write operations: create branches, commit files, delete files."""

import io
import zipfile
from typing import Any

from src.cache import tree_cache
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
            # Annotated tags point to a tag object, not a commit — dereference it.
            # create_ref requires a commit SHA; passing a tag object SHA yields HTTP 422.
            if ref_data["object"]["type"] == "tag":
                tag = await client._get(f"/repos/{owner}/{repo}/git/tags/{sha}")
                sha = tag["object"]["sha"]
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

    # Invalidate the tree cache so subsequent find_files/search_code calls
    # see the new commit rather than the pre-push state.
    tree_cache.invalidate(f"tree:{owner}/{repo}:{branch}")

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


async def get_workflow_run_logs(
    client: GitHubClient,
    owner: str,
    repo: str,
    run_id: int,
    max_chars: int = 20000,
) -> str:
    """Fetch logs for a workflow run, highlighting failed steps.

    Strategy:
    1. GET jobs → identify failed jobs / steps
    2. Download the logs zip
    3. For each failed job, extract the relevant step log(s)
    4. Fall back to showing all logs if no failures are detected
    """
    # ── Step 1: jobs summary ──────────────────────────────────────────
    jobs_data = await client.get_workflow_run_jobs(owner, repo, run_id)
    jobs: list[dict] = jobs_data.get("jobs", [])

    if not jobs:
        return f"No jobs found for run {run_id}."

    # Build a summary header and collect the names of failed jobs
    summary_lines = [f"Run #{run_id} — {len(jobs)} job(s):\n"]
    failed_job_names: set[str] = set()
    failed_steps_by_job: dict[str, list[str]] = {}

    for job in jobs:
        conclusion = job.get("conclusion") or job.get("status", "unknown")
        icon = {"success": "✓", "failure": "✗", "cancelled": "⊘", "skipped": "—"}.get(
            conclusion, "?"
        )
        summary_lines.append(f"  {icon} {job['name']}  ({conclusion})")

        if conclusion == "failure":
            failed_job_names.add(job["name"])
            failed_steps: list[str] = []
            for step in job.get("steps", []):
                step_conclusion = step.get("conclusion") or ""
                step_icon = {"success": "✓", "failure": "✗", "skipped": "—"}.get(
                    step_conclusion, "?"
                )
                summary_lines.append(
                    f"      {step_icon} step {step['number']}: {step['name']}  ({step_conclusion})"
                )
                if step_conclusion == "failure":
                    failed_steps.append(step["name"])
            failed_steps_by_job[job["name"]] = failed_steps

    summary = "\n".join(summary_lines)

    # ── Step 2: download logs zip ─────────────────────────────────────
    try:
        zip_bytes = await client.download_workflow_run_logs(owner, repo, run_id)
    except GitHubAPIError as e:
        return f"{summary}\n\n⚠ Could not download logs: {e}"

    # ── Step 3: extract relevant log content ──────────────────────────
    target_jobs = failed_job_names if failed_job_names else {j["name"] for j in jobs}
    target_steps = failed_steps_by_job  # only non-empty when there are failures

    extracted: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Zip entries look like: "{job_name}/1_Set up job.txt"
            # or "{N}_{job_name}.txt" at the top level for some runners.
            for name in sorted(zf.namelist()):
                parts = name.split("/", 1)
                if len(parts) == 2:
                    job_folder, step_file = parts
                else:
                    job_folder, step_file = "", parts[0]

                # Match by job name substring (GitHub slugifies the name in the path)
                matched_job = next(
                    (
                        j
                        for j in target_jobs
                        if _slugify(j) in _slugify(job_folder)
                        or _slugify(job_folder) in _slugify(j)
                    ),
                    None,
                )
                if matched_job is None:
                    continue

                # If we know the specific failed steps, only show those
                failed_step_names = target_steps.get(matched_job, [])
                if failed_step_names:
                    step_match = any(
                        _slugify(s) in _slugify(step_file) or _slugify(step_file) in _slugify(s)
                        for s in failed_step_names
                    )
                    if not step_match:
                        continue

                raw = zf.read(name).decode("utf-8", errors="replace")
                # Strip the leading timestamp on each line (GitHub prepends "2024-01-01T...")
                lines = [_strip_timestamp(ln) for ln in raw.splitlines()]
                content = "\n".join(lines).strip()
                if content:
                    extracted.append(f"### {name}\n{content}")
    except zipfile.BadZipFile:
        return f"{summary}\n\n⚠ Downloaded data is not a valid zip file."

    if not extracted:
        return f"{summary}\n\n(No matching log entries found in zip.)"

    logs_text = "\n\n".join(extracted)

    # ── Step 4: truncate if needed ────────────────────────────────────
    truncated = ""
    if len(logs_text) > max_chars:
        logs_text = logs_text[:max_chars]
        truncated = f"\n\n… (truncated to {max_chars:,} chars)"

    header = "FAILED STEP LOGS" if failed_job_names else "LOGS"
    return f"{summary}\n\n── {header} ──\n\n{logs_text}{truncated}"


def _slugify(s: str) -> str:
    """Lowercase and strip non-alphanumeric for fuzzy name matching."""
    return "".join(c.lower() if c.isalnum() else "_" for c in s)


def _strip_timestamp(line: str) -> str:
    """Remove the ISO-8601 timestamp GitHub prepends to each log line."""
    # Format: "2024-01-01T10:00:00.0000000Z <content>"
    if len(line) > 29 and line[10] == "T" and line[19] in (".", ":") and "Z " in line[:32]:
        idx = line.index("Z ") + 2
        return line[idx:]
    return line


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
