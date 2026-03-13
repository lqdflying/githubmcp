"""Async GitHub API client wrapping REST and GraphQL APIs."""

import base64
from dataclasses import dataclass

import httpx


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"GitHub API error ({status_code}): {message}")


@dataclass
class RateLimitInfo:
    remaining: int
    limit: int
    reset_at: int  # Unix timestamp


class GitHubClient:
    """Async client for GitHub REST and GraphQL APIs using a PAT."""

    REST_BASE = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: str):
        self._token = token
        self._http = httpx.AsyncClient(
            base_url=self.REST_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._graphql_http = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self.rate_limit: RateLimitInfo | None = None

    async def close(self):
        await self._http.aclose()
        await self._graphql_http.aclose()

    # ── Rate limit tracking ──────────────────────────────────────────

    def _update_rate_limit(self, response: httpx.Response):
        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset_at = response.headers.get("X-RateLimit-Reset")
        if remaining is not None and limit is not None and reset_at is not None:
            self.rate_limit = RateLimitInfo(
                remaining=int(remaining),
                limit=int(limit),
                reset_at=int(reset_at),
            )

    # ── REST helpers ─────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        response = await self._http.get(path, params=params)
        self._update_rate_limit(response)
        if response.status_code == 401:
            raise GitHubAPIError(401, "Invalid or expired GitHub token.")
        if response.status_code == 403:
            msg = "Access denied or rate limit exceeded."
            body = response.json() if response.content else {}
            if isinstance(body, dict) and "message" in body:
                msg = body["message"]
            raise GitHubAPIError(403, msg)
        if response.status_code == 404:
            raise GitHubAPIError(404, "Resource not found.")
        if response.status_code == 422:
            body = response.json() if response.content else {}
            msg = body.get("message", "Unprocessable entity")
            raise GitHubAPIError(422, msg)
        response.raise_for_status()
        return response.json()

    # ── GraphQL helper ───────────────────────────────────────────────

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        response = await self._graphql_http.post(self.GRAPHQL_URL, json=payload)
        self._update_rate_limit(response)
        if response.status_code == 401:
            raise GitHubAPIError(401, "Invalid or expired GitHub token.")
        if response.status_code == 403:
            raise GitHubAPIError(403, "Access denied or rate limit exceeded.")
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            messages = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise GitHubAPIError(400, f"GraphQL errors: {messages}")
        return data["data"]

    # ── Repository endpoints ─────────────────────────────────────────

    async def get_repo(self, owner: str, repo: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}")

    async def get_languages(self, owner: str, repo: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/languages")

    # ── Contents endpoints ───────────────────────────────────────────

    async def get_contents(self, owner: str, repo: str, path: str = "", ref: str | None = None) -> dict | list:
        params = {}
        if ref:
            params["ref"] = ref
        return await self._get(f"/repos/{owner}/{repo}/contents/{path}", params=params)

    # ── Git Data endpoints ───────────────────────────────────────────

    async def get_tree(self, owner: str, repo: str, tree_sha: str, recursive: bool = False) -> dict:
        params = {}
        if recursive:
            params["recursive"] = "1"
        return await self._get(f"/repos/{owner}/{repo}/git/trees/{tree_sha}", params=params)

    async def get_blob(self, owner: str, repo: str, sha: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/git/blobs/{sha}")

    async def get_ref(self, owner: str, repo: str, ref: str) -> dict:
        """Resolve a branch/tag name to a commit SHA."""
        try:
            return await self._get(f"/repos/{owner}/{repo}/git/ref/heads/{ref}")
        except GitHubAPIError:
            # Try as a tag
            return await self._get(f"/repos/{owner}/{repo}/git/ref/tags/{ref}")

    async def get_commit(self, owner: str, repo: str, sha: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/git/commits/{sha}")

    # ── Branches ─────────────────────────────────────────────────────

    async def list_branches(self, owner: str, repo: str, per_page: int = 100) -> list:
        return await self._get(f"/repos/{owner}/{repo}/branches", params={"per_page": per_page})

    # ── Commits ──────────────────────────────────────────────────────

    async def list_commits(
        self,
        owner: str,
        repo: str,
        sha: str | None = None,
        path: str | None = None,
        per_page: int = 20,
    ) -> list:
        params: dict = {"per_page": per_page}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        return await self._get(f"/repos/{owner}/{repo}/commits", params=params)

    # ── Compare (diff) ───────────────────────────────────────────────

    async def compare(self, owner: str, repo: str, base: str, head: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")

    # ── Code search ──────────────────────────────────────────────────

    async def search_code(self, query: str, owner: str, repo: str, per_page: int = 30) -> dict:
        full_query = f"{query} repo:{owner}/{repo}"
        return await self._get("/search/code", params={"q": full_query, "per_page": per_page})

    # ── Blame (GraphQL) ──────────────────────────────────────────────

    async def get_blame(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> list:
        query = """
        query($owner: String!, $repo: String!, $ref: String!, $path: String!) {
          repository(owner: $owner, name: $repo) {
            object(expression: $ref) {
              ... on Commit {
                blame(path: $path) {
                  ranges {
                    startingLine
                    endingLine
                    commit {
                      oid
                      message
                      author {
                        name
                        email
                        date
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "path": path,
        }
        data = await self.graphql(query, variables)
        obj = data.get("repository", {}).get("object")
        if not obj or "blame" not in obj:
            raise GitHubAPIError(404, f"Could not get blame for {path} at {ref}")
        return obj["blame"]["ranges"]

    # ── Token validation ─────────────────────────────────────────────

    async def validate_token(self) -> dict:
        """Validate the PAT by calling /user. Returns user info or raises."""
        return await self._get("/user")

    # ── File content helper ──────────────────────────────────────────

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str | None = None) -> str:
        """Get decoded text content of a file. Falls back to Blobs API for large files."""
        try:
            data = await self.get_contents(owner, repo, path, ref)
        except GitHubAPIError:
            raise

        if isinstance(data, list):
            raise GitHubAPIError(400, f"'{path}' is a directory, not a file.")

        # Contents API returns base64 for files ≤ 1MB
        if data.get("content"):
            content_b64 = data["content"]
            return base64.b64decode(content_b64).decode("utf-8", errors="replace")

        # For files > 1MB, use the Blobs API via the sha
        if data.get("sha"):
            blob = await self.get_blob(owner, repo, data["sha"])
            if blob.get("encoding") == "base64":
                return base64.b64decode(blob["content"]).decode("utf-8", errors="replace")
            return blob.get("content", "")

        raise GitHubAPIError(400, f"Could not read content of '{path}'.")

    # ── Tree resolution helper ───────────────────────────────────────

    async def get_full_tree(self, owner: str, repo: str, ref: str | None = None) -> list[dict]:
        """Get the full recursive tree for a repo at a given ref."""
        # Resolve ref to a commit SHA, then get the tree SHA
        if ref:
            ref_data = await self.get_ref(owner, repo, ref)
            commit_sha = ref_data["object"]["sha"]
        else:
            repo_data = await self.get_repo(owner, repo)
            default_branch = repo_data["default_branch"]
            ref_data = await self.get_ref(owner, repo, default_branch)
            commit_sha = ref_data["object"]["sha"]

        # The ref might point to a commit directly, or to a tag object
        if ref_data["object"]["type"] == "tag":
            tag = await self._get(f"/repos/{owner}/{repo}/git/tags/{commit_sha}")
            commit_sha = tag["object"]["sha"]

        commit_data = await self.get_commit(owner, repo, commit_sha)
        tree_sha = commit_data["tree"]["sha"]

        tree_data = await self.get_tree(owner, repo, tree_sha, recursive=True)
        return tree_data.get("tree", [])
