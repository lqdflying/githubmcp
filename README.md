# GitHub Repo Reader & Code Tools MCP Server

An MCP (Model Context Protocol) server built with **FastMCP** that gives AI agents — such as **VS Code Copilot** and **Copilot Studio** — the ability to read, explore, and **write** GitHub repositories. The server uses your **GitHub Personal Access Token (PAT)** for all GitHub API calls. MCP clients authenticate using a static bearer token, GitHub OAuth, or both.

---

## Table of Contents

- [Features](#features-26-mcp-tools)
- [Example Prompts](#example-prompts)
- [How Authentication Works](#how-authentication-works)
- [Prerequisites](#prerequisites)
- [Setup Scenarios](#setup-scenarios)
- [Account Access Control](#account-access-control)
- [Creating a GitHub App](#creating-a-github-app)
- [Environment Variables Reference](#environment-variables-reference)
- [Docker Deployment](#docker-deployment)
- [Nginx Reverse Proxy](#nginx-reverse-proxy)
- [VS Code Integration](#vs-code-integration)
- [Copilot Studio Integration](#copilot-studio-integration)
- [Tool Reference & Examples](#tool-reference--examples)
- [Architecture](#architecture)
- [Development](#development)

---

## Features (29 MCP Tools)

### Read Tools (always available)

| # | Tool | What it does |
|---|------|-------------|
| 1 | `read_file` | Read a file's full contents or a specific line range |
| 2 | `list_directory` | List files and folders inside a directory |
| 3 | `find_files` | Find files matching a glob pattern (e.g. `**/*.py`) |
| 4 | `search_code` | Search for text or regex patterns across all repo files |
| 5 | `get_file_summary` | Get file size, line count, detected language, and a content preview |
| 6 | `list_branches` | List all branches in a repository |
| 7 | `get_commits` | View commit history for a repo or a specific file |
| 8 | `get_diff` | Compare two branches, tags, or commits |
| 9 | `get_blame` | See which commit last changed each line of a file |
| 10 | `get_file_history` | List commits that touched a specific file |
| 11 | `get_repo_info` | Get repository metadata (description, stars, topics, etc.) |
| 12 | `get_repo_structure` | View the full folder and file tree |
| 13 | `get_languages` | See the programming language breakdown |
| 14 | `get_rate_limit` | Check remaining GitHub API quota |

### Write Tools (disabled when `MCP_READ_ONLY=true`)

| # | Tool | What it does |
|---|------|-------------|
| 15 | `create_branch` | Create a new branch from any ref or the default branch |
| 16 | `push_files` | Commit one or more files in a single atomic commit |
| 17 | `delete_file` | Delete a file from a branch |
| 18 | `create_pull_request` | Open a new pull request (supports draft) |
| 19 | `list_pull_requests` | List PRs filtered by state, head branch, or base branch |
| 20 | `get_pull_request` | Get PR details: status, diff stats, mergeable, description |
| 21 | `merge_pull_request` | Merge a PR (merge / squash / rebase) |
| 22 | `add_pr_comment` | Add a comment to a pull request |
| 23 | `create_issue` | Create a new issue with optional labels |
| 24 | `list_workflow_runs` | List recent CI/CD workflow runs with status |
| 25 | `get_workflow_run_logs` | Download and show logs for a run, highlighting failed steps |
| 26 | `trigger_workflow` | Trigger a `workflow_dispatch` event to run a CI workflow |

### Task Tracking Tools (always available)

| # | Tool | What it does |
|---|------|-------------|
| 27 | `todo_write` | Initialise or replace the in-session task list |
| 28 | `todo_update` | Mark a single task as `pending`, `in_progress`, or `completed` by index |
| 29 | `todo_read` | Read the current task list and completion progress |

These tools give the AI agent an in-process task list so it can track multi-step work, check off completed steps one by one, and show progress throughout a long session. State is in-memory and resets on server restart.

---

## Example Prompts

### Reading & exploring

```
What is the folder structure of owner/repo?
Show me the last 10 commits on the main branch of owner/repo
Search for all TODO comments in owner/repo
What languages does owner/repo use?
Show me the diff between main and develop in owner/repo
Who last modified line 42 in src/server.py in owner/repo?
Read the file src/auth.py in owner/repo
```

### Full AI coding loop

The write tools unlock an end-to-end workflow: read the codebase, make changes, run CI, diagnose failures, and open a PR — without leaving your AI agent.

**Example: fix a bug and open a PR**

```
In owner/repo:
1. Read src/auth.py and find the bug in the login function
2. Create a branch called fix/login-bug
3. Fix the bug and push the updated file
4. Check whether CI passes — if it fails, read the logs and fix the issue
5. Once CI is green, open a pull request to main with a clear description
```

**Example: add a feature from scratch**

```
In owner/repo:
1. Look at the project structure and understand how it's organised
2. Create a branch called feature/user-profile
3. Add a new user profile endpoint following the patterns in src/routes/
4. Push all the new files in one commit
5. Wait for CI to finish; if there are test failures show me the logs
6. Open a draft PR titled "Add user profile endpoint"
```

**Example: set up CI on a repo that has none**

```
In owner/repo:
1. Check what language and build tools the project uses
2. Create a branch called ci/add-github-actions
3. Write an appropriate .github/workflows/ci.yml based on the project type
4. Push it, then confirm the workflow appears and triggers correctly
5. Open a PR to merge it into main
```

**Example: investigate a failing CI run**

```
In owner/repo, the latest CI run on branch feature/x failed.
Show me which step failed and the relevant log output so I can fix it.
```

### Task tracking

The todo tools let the agent maintain a visible checklist throughout a long session — steps get checked off one by one as work progresses.

**Example: track progress on a multi-file refactor**

```
In owner/repo, refactor the authentication module:
- Split src/auth.py into separate files for token, oauth, and middleware
- Update all imports across the codebase
- Make sure tests still pass after each change
Use the todo list to track each step so I can follow your progress.
```

The agent will initialise a task list at the start, mark each step `in_progress` before working on it, and check it off (`completed`) when done:

```
Tasks (0/4 completed):
  ◉ Read current auth.py and plan the split  [in_progress]
  ○ Create token.py, oauth.py, middleware.py  [pending]
  ○ Update imports across codebase            [pending]
  ○ Verify tests pass                         [pending]
```

**Example: batch issue triage**

```
In owner/repo, go through the 5 oldest open issues and for each one:
- Read the issue description
- Find the relevant code
- Leave a comment with a diagnosis and suggested fix
Track each issue as a todo item so I can see which ones are done.
```

**Example: multi-repo setup**

```
Set up the same CI pipeline in these three repos: org/api, org/frontend, org/workers.
For each repo:
1. Create a branch ci/standardise
2. Push the shared .github/workflows/ci.yml
3. Open a PR to main
Use a todo list with one item per repo so I can track progress.
```

---

## How Authentication Works

There are **two separate and independent authentication layers**:

```
MCP Client (VS Code / Copilot Studio)
        │
        │  Layer 1 — "Who are you?"
        │  Proved by: MCP_API_TOKEN (static)
        │              or GitHub OAuth token
        ▼
MCP Server (this server)
        │
        │  Layer 2 — "Fetch GitHub data"
        │  Always uses: GITHUB_PAT (server's own token)
        │  The client's OAuth token is never used here
        ▼
GitHub API
```

**What this means in practice:**

- Which GitHub repos the server can access is determined entirely by `GITHUB_PAT`
- OAuth only controls *who is allowed to call the server*, not *which repos they can see*
- Even after OAuth sign-in, a user can only access repos that `GITHUB_PAT` has permission for
- `ALLOWED_GITHUB_LOGINS` is the mechanism to restrict OAuth to specific GitHub accounts

### Auth Modes

| `MCP_AUTH_MODE` | Who can connect | Best for |
|-----------------|----------------|---------|
| `token` | Anyone with the `MCP_API_TOKEN` value | Local / trusted environments |
| `oauth` | GitHub accounts listed in `ALLOWED_GITHUB_LOGINS` | Remote deployments requiring identity |
| `both` *(default)* | Either token or GitHub OAuth | Supporting multiple client types simultaneously |

---

## Prerequisites

- **Python 3.12+** (direct) or **Docker** (containerised)
- A **GitHub Personal Access Token** — this is what the server uses to call the GitHub API:

  | | Classic token | Fine-grained token |
  |---|---|---|
  | **Read tools only** | `public_repo` (public) or `repo` (private) | `Contents: Read` + `Metadata: Read` |
  | **Read + Write tools** | `repo` | `Contents: Read+Write` + `Metadata: Read` + `Pull requests: Read+Write` + `Actions: Read+Write` |

  Set `MCP_READ_ONLY=true` in your `.env` if your token only has read permissions — this disables all write tools at startup so they are hidden from AI agents entirely.

### Creating a GitHub PAT

1. Go to **[GitHub Settings → Developer Settings → Personal Access Tokens](https://github.com/settings/tokens)**
2. Click **Generate new token (classic)** or **Fine-grained tokens → Generate new token**
3. For classic: tick the **`repo`** scope
4. For fine-grained: follow the steps below
5. Set an expiry and click **Generate token**
6. **Copy the token immediately** — GitHub only shows it once

#### Fine-grained token setup (recommended)

**Repository access** — choose one:

| Option | When to use |
|--------|-------------|
| **Only select repositories** | Limit the token to specific repos (more secure; you pick which repos) |
| **All repositories** | Use when you want the MCP to access any repo your account can see, including arbitrary public repos |

> If you choose *Only select repositories*, the MCP can only access the repos you explicitly select here. Pointing it at any other repo (even a public one) will return a 403/404.

**Permissions** — under *Repository permissions*, set:

| Permission | Read-only mode | Read+Write mode | Notes |
|------------|:--------------:|:---------------:|-------|
| **Contents** | Read | Read+Write | **Required** — files, trees, blobs, commits, branches, diffs, blame |
| **Metadata** | Read | Read | **Required** — repo info, language breakdown (auto-selected by GitHub) |
| **Pull requests** | — | Read+Write | Required for `create_pull_request`, `merge_pull_request`, `add_pr_comment`, `list_pull_requests` |
| **Actions** | — | Read+Write | Required for `list_workflow_runs`, `get_workflow_run_logs`, `trigger_workflow` |

> For read-only use, only `Contents: Read` and `Metadata: Read` are required. Set `MCP_READ_ONLY=true` to hide write tools from AI agents when using a read-only token.

---

## Setup Scenarios

Pick the scenario that matches your use case.

---

### Scenario 1 — Local use with VS Code (simplest, no OAuth needed)

Run the server on your own machine and connect from VS Code locally. No GitHub OAuth App required.

**Step 1 — Clone and install**

```bash
git clone <this-repo-url>
cd githubmcp
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

**Step 2 — Create your `.env`**

```bash
cp .env.example .env
```

Edit `.env` — only two values are needed:

```env
GITHUB_PAT=ghp_your_github_pat_here
MCP_AUTH_MODE=token
MCP_API_TOKEN=your_secret_token_here
```

Generate a secure token:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Step 3 — Start the server**

```bash
python server.py
```

You should see:
```
Authenticated as GitHub user: your-username
```

**Step 4 — Connect VS Code** (see [VS Code Integration — Option A](#option-a-static-token-local))

---

### Scenario 2 — Remote server, VS Code with GitHub OAuth

The server is deployed on a remote machine. VS Code signs in with GitHub OAuth — no static token needed on the client.

**Step 1 — Create a GitHub App**

See [Creating a GitHub App](#creating-a-github-app). Add this callback URL:
```
https://your-domain/auth/callback
```

**Step 2 — Configure `.env` on the server**

```env
GITHUB_PAT=ghp_your_github_pat_here
MCP_AUTH_MODE=oauth
GITHUB_CLIENT_ID=your_github_app_client_id
GITHUB_CLIENT_SECRET=your_github_app_client_secret
BASE_URL=https://your-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

**Step 3 — Deploy**

```bash
docker compose up -d
```

**Step 4 — Connect VS Code** (see [VS Code Integration — Option B](#option-b-github-oauth-remote-server))

VS Code will open a browser sign-in prompt the first time it connects.

---

### Scenario 3 — Remote server, Copilot Studio with GitHub OAuth

Connect Copilot Studio (via Power Automate custom connector) using GitHub OAuth.

**Step 1 — Create a GitHub App**

See [Creating a GitHub App](#creating-a-github-app). Leave the Copilot Studio callback URL blank for now — you'll get it from Power Automate in Step 4, then add it to the GitHub App.

**Step 2 — Configure `.env` on the server**

```env
GITHUB_PAT=ghp_your_github_pat_here
MCP_AUTH_MODE=oauth
GITHUB_CLIENT_ID=your_github_app_client_id
GITHUB_CLIENT_SECRET=your_github_app_client_secret
BASE_URL=https://your-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

**Step 3 — Deploy**

```bash
docker compose up -d
```

**Step 4 — Connect Copilot Studio** (see [Copilot Studio Integration — OAuth](#option-b-github-oauth-via-power-automate))

---

### Scenario 4 — Remote server, VS Code OAuth + Copilot Studio OAuth simultaneously

Use a single **GitHub App** (supports up to 10 callback URLs) so both VS Code and Copilot Studio authenticate via OAuth on the same server with the same credentials.

**Step 1 — Create a GitHub App**

See [Creating a GitHub App](#creating-a-github-app). Add **both** callback URLs:
```
https://your-domain/auth/callback
https://global.consent.azure-apim.net/redirect
```

**Step 2 — Configure `.env`**

```env
GITHUB_PAT=ghp_your_github_pat_here
MCP_AUTH_MODE=both
MCP_API_TOKEN=your_secret_token_here
GITHUB_CLIENT_ID=your_github_app_client_id
GITHUB_CLIENT_SECRET=your_github_app_client_secret
BASE_URL=https://your-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

With `MCP_AUTH_MODE=both`:
- VS Code and Copilot Studio both connect via GitHub OAuth
- Static token (`MCP_API_TOKEN`) is also accepted for automation/testing
- All clients use the same `/mcp` endpoint
- A single GitHub App handles all OAuth callbacks — no need for multiple apps

---

## Account Access Control

`ALLOWED_GITHUB_LOGINS` is a comma-separated list of GitHub usernames permitted to sign in via OAuth.

> ⚠️ **If left empty, any valid GitHub account can authenticate via OAuth.** Always set this when deploying for personal or team use.

### Allow only your own account

```env
ALLOWED_GITHUB_LOGINS=your-github-username
```

### Allow multiple accounts (you + trusted others)

```env
ALLOWED_GITHUB_LOGINS=your-username,colleague-username,bot-account
```

All listed accounts receive identical access to all available tools. The check is case-insensitive.

### How the allowlist works

When an OAuth token arrives, the server calls GitHub to verify it and retrieve the authenticated user's login. If that login is not in the list, the request is rejected with a `401`. The audit log records:

```
AUTH success method=oauth login=your-username
AUTH rejected method=oauth login=someone-else reason=login_not_allowlisted
```

> `ALLOWED_GITHUB_LOGINS` only applies to OAuth sign-ins. Static token auth (`MCP_API_TOKEN`) is not affected.

---

## Creating a GitHub App

Required for Scenarios 2, 3, and 4. GitHub Apps support **up to 10 callback URLs**, so a single app handles VS Code, Copilot Studio, and any other OAuth client simultaneously — no need to create multiple apps.

1. Go to **[GitHub → Settings → Developer Settings → GitHub Apps](https://github.com/settings/apps/new)**
2. Fill in the form:
   - **GitHub App name**: e.g. `my-githubmcp` (must be globally unique)
   - **Homepage URL**: your server URL, e.g. `https://your-domain`
   - **Callback URL**: add one per line (see table below)
   - **Webhook**: uncheck **Active** (not needed)
3. Under **Account permissions**:
   - **Email addresses** → Read-only
   - **Profile** → Read-only
4. Under **"Where can this GitHub App be installed?"** → select **Only on this account**
5. Click **Create GitHub App**
6. Note the **Client ID**
7. Click **Generate a new client secret** and copy it immediately

### Which callback URLs to add

| Integration | Callback URL |
|-------------|--------------|
| VS Code (native MCP OAuth) | `https://your-domain/auth/callback` |
| Power Automate / Copilot Studio | The Redirect URL generated by Power Automate — get it from the connector Security tab after first save, then add it here |

> You can add all callback URLs upfront or add the Power Automate one later — GitHub Apps let you edit them at any time.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_PAT` | **Yes** | — | GitHub PAT used for all GitHub API calls. Server exits on startup if missing or invalid. |
| `MCP_AUTH_MODE` | No | `both` | `token` — static token only; `oauth` — GitHub OAuth only; `both` — either method accepted. **Note: `both` requires all three OAuth vars (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `BASE_URL`) to be set — if you only want token auth, use `token` instead.** |
| `MCP_AUTH_AUDIT_LOG` | No | `true` | Log auth decisions (method, login, allowlist result). Never logs token values. |
| `MCP_API_TOKEN` | Conditional | — | Required when `MCP_AUTH_MODE=token` or `both`. The shared secret clients send as a Bearer token. |
| `GITHUB_CLIENT_ID` | Conditional | — | GitHub App client ID. Required when OAuth is enabled. |
| `GITHUB_CLIENT_SECRET` | Conditional | — | GitHub App client secret. Required when OAuth is enabled. |
| `BASE_URL` | Conditional | — | Public HTTPS URL of this server, e.g. `https://your-domain`. Required when OAuth is enabled (used for OAuth metadata and callbacks). |
| `GITHUB_OAUTH_SCOPES` | No | `user` | Scopes requested during GitHub OAuth. `user` is sufficient for identity verification. Child scopes like `read:user` are automatically normalised to their parent (`user`) at startup, so both values behave identically. |
| `ALLOWED_GITHUB_LOGINS` | **Strongly recommended** | *(empty = allow all)* | Comma-separated GitHub usernames permitted for OAuth. **Empty means any GitHub account can sign in.** |
| `MCP_STATELESS` | No | `true` | `true` — stateless mode (default, recommended): new transport per request, survives restarts with no stale session issues. `false` — stateful mode: enables SSE event replay via Redis so clients can resume a dropped stream using `Last-Event-ID`; requires both Upstash vars; sessions are in-memory so clients must re-connect after a server restart. |
| `UPSTASH_REDIS_REST_URL` | When `MCP_STATELESS=false` | — | Upstash REST URL from the Upstash console (e.g. `https://host.upstash.io`). Both Upstash vars must be set together. Ignored when `MCP_STATELESS=true`. |
| `UPSTASH_REDIS_REST_TOKEN` | When `MCP_STATELESS=false` | — | Upstash REST token from the Upstash console. Both Upstash vars must be set together. Ignored when `MCP_STATELESS=true`. |
| `MCP_READ_ONLY` | No | `false` | `true` — disable all write/PR/CI tools at startup. Use when `GITHUB_PAT` only has read permissions. Read tools (`read_file`, `search_code`, `get_diff`, etc.) are always available regardless of this setting. |
| `HOST` | No | `0.0.0.0` | Network interface to bind to |
| `PORT` | No | `8000` | Port to listen on |

> **Note — VS Code `Failed to parse message: ""` warning**
> When `MCP_STATELESS=false` and Upstash Redis is configured, the server uses an `EventStore` (FastMCP's built-in Redis-backed event store). The MCP Python SDK then sends an empty SSE priming frame (`data: ""`) on every `GET /mcp` connection to support client reconnection. VS Code's MCP client logs `Failed to parse message: ""` when it receives this frame. This warning is **harmless** — tools are discovered and OAuth works normally. It is triggered by the `EventStore`, not by stateful/stateless mode itself. A fix requires VS Code to silently skip empty SSE frames before JSON parsing.

---

## Docker Deployment

### 1. Prepare the environment file

```bash
cp .env.example .env
# Edit .env — fill in GITHUB_PAT, and MCP_API_TOKEN and/or OAuth vars depending on your scenario
```

Example `.env` for dual auth (Scenario 4):

```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=both
MCP_AUTH_AUDIT_LOG=true
MCP_API_TOKEN=your_secret_mcp_token_here
GITHUB_CLIENT_ID=your_oauth_client_id
GITHUB_CLIENT_SECRET=your_oauth_client_secret
BASE_URL=https://your-domain
GITHUB_OAUTH_SCOPES=user
ALLOWED_GITHUB_LOGINS=your-github-username
HOST=0.0.0.0
PORT=8000
```

### 2. Start with Docker Compose

```bash
docker compose up -d          # start in background
docker compose logs -f        # follow logs
docker compose down           # stop
```

### 3. Build image locally (optional)

```bash
docker build -t github-repo-reader-mcp .
```

---

## Nginx Reverse Proxy

Required for production HTTPS deployments. GitHub OAuth only allows HTTPS callback URLs.

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name your-domain;
    return 301 https://$host$request_uri;
}

# HTTPS reverse proxy to the MCP container
server {
    listen 443 ssl http2;
    server_name your-domain;

    ssl_certificate     /etc/nginx/cert/your-domain.crt;
    ssl_certificate_key /etc/nginx/cert/your-domain.key;

    ssl_protocols             TLSv1.2 TLSv1.3;
    ssl_ciphers               ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:!aNULL:!eNULL:!EXPORT:!MD5:!RC4:!3DES;
    ssl_prefer_server_ciphers on;
    ssl_session_cache         shared:SSL:10m;
    ssl_session_timeout       10m;

    add_header Strict-Transport-Security "max-age=31536000" always;

    access_log /var/log/nginx/githubmcp.access.log;
    error_log  /var/log/nginx/githubmcp.error.log;

    location / {
        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Required for MCP SSE streaming (long-lived HTTP connections)
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";

        proxy_connect_timeout 300s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;
        proxy_buffering       off;
    }
}
```

Replace `your-domain` with your actual domain and update the certificate paths.

---

## VS Code Integration

### Option A: Static Token (local) {#option-a-static-token-local}

Best when the server runs locally on the same machine as VS Code.

Add to `.vscode/mcp.json` in your project (or `settings.json` under `"mcp"`):

```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer your_secret_mcp_token_here"
      }
    }
  }
}
```

Requires `MCP_AUTH_MODE=token` or `MCP_AUTH_MODE=both` with `MCP_API_TOKEN` set.

### Option B: GitHub OAuth (remote server) {#option-b-github-oauth-remote-server}

Best when the server is deployed remotely. No token in the config — VS Code handles the OAuth flow automatically.

```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "https://your-domain/mcp"
    }
  }
}
```

On first use, VS Code detects that the server requires OAuth (from the `401` response + discovery metadata), opens a browser window, and asks you to sign in with GitHub. After authorising, VS Code caches the token — you won't be prompted again until it expires.

Requires `MCP_AUTH_MODE=oauth` or `MCP_AUTH_MODE=both`, all three OAuth env vars set, and `ALLOWED_GITHUB_LOGINS=your-username`.

The GitHub App callback URL for VS Code must be set to `https://your-domain/auth/callback`.

### Using in VS Code Copilot Chat

Once connected, open **Copilot Chat** (`Ctrl+Shift+I` / `Cmd+Shift+I`), switch to **Agent mode**, and try:

```
What is the folder structure of owner/repo?
Show me the last 10 commits on the main branch of owner/repo
Search for all TODO comments in owner/repo
What languages does microsoft/vscode use?
Show me the diff between main and develop in owner/repo
Who last modified line 42 in src/server.py in owner/repo?
Read the file src/auth.py in owner/repo
```

---

## Copilot Studio Integration

> **Recommended testing order:** Start with Option A (static token) to confirm the MCP tools work end-to-end in your agent. Switch to Option B (OAuth) once that is verified.

### Option A: Static Token {#option-a-static-token-simple}

The server must be running with `MCP_AUTH_MODE=token` or `MCP_AUTH_MODE=both` and `MCP_API_TOKEN` set.

1. In [Copilot Studio](https://copilotstudio.microsoft.com), open your agent
2. Go to **Actions → Add an action → Model Context Protocol**
3. Set **Server URL** to `https://your-domain/mcp`
4. Under **Authentication**, choose **API Key** or **Bearer token** and enter your `MCP_API_TOKEN` value
5. Copilot Studio will discover all available tools automatically — select the ones you want to expose
6. Save and publish

Test by asking a question in your agent that requires a tool, e.g.:
```
What is the folder structure of owner/repo?
```

### Option B: GitHub OAuth (native MCP) {#option-b-github-oauth-via-power-automate}

Copilot Studio's native MCP action supports OAuth discovery. When you add the server URL, Copilot Studio reads the server's `/.well-known/oauth-authorization-server` metadata, registers a client via Dynamic Client Registration (DCR), and handles the sign-in flow — the same way VS Code does.

The server must be running with `MCP_AUTH_MODE=oauth` or `MCP_AUTH_MODE=both` and all three OAuth env vars set.

> **Important:** Copilot Studio authenticates via **this server's own OAuth proxy** (endpoints at `https://your-domain/authorize` and `https://your-domain/token`) — **not** directly against `github.com`. The server proxies the sign-in to GitHub on behalf of the client. Do not configure Power Automate or Copilot Studio to point at GitHub's OAuth endpoints directly — that would produce a raw GitHub token which this server cannot accept (it expects the FastMCP JWT issued by its own token endpoint).

**Step 1 — Add the MCP server**

1. In Copilot Studio → **Actions → Add an action → Model Context Protocol**
2. Set **Server URL** to `https://your-domain/mcp`
3. Copilot Studio detects that OAuth is required and begins the discovery flow

**Step 2 — Sign in**

1. Copilot Studio redirects to your GitHub App's sign-in page
2. Authorise the app
3. Only accounts listed in `ALLOWED_GITHUB_LOGINS` will be permitted

**Step 3 — Select tools and save**

Select the tools you want to expose in your agent and save.

**Step 4 — Add the Power Automate callback URL to your GitHub App**

Copilot Studio generates a redirect URL during registration. Copy it and add it as an additional **Callback URL** in your [GitHub App settings](https://github.com/settings/apps).

### Example prompts for Copilot Studio agents

```
What is the folder structure of owner/repo?
Find all Python files in owner/repo
Show me recent commits in owner/repo
Summarise what the file src/main.py does in owner/repo
Search for the function calculateTotal in owner/repo
What is the language breakdown of owner/repo?
```

---

## Tool Reference & Examples

All tools accept `owner` (GitHub username or organisation) and `repo` (repository name) as the first two parameters.

### File Operations

**Read an entire file**
```
read_file(owner="microsoft", repo="vscode", path="package.json")
```

**Read a specific line range**
```
read_file(owner="microsoft", repo="vscode", path="src/vs/base/common/uri.ts", start_line=1, end_line=50)
```

**List a directory**
```
list_directory(owner="microsoft", repo="vscode", path="src/vs/editor")
```

**List the root directory**
```
list_directory(owner="owner", repo="repo", path="")
```

**Find all Python files**
```
find_files(owner="owner", repo="repo", pattern="**/*.py")
```

**Find test files**
```
find_files(owner="owner", repo="repo", pattern="tests/**/*.py")
```

**Find config files**
```
find_files(owner="owner", repo="repo", pattern="*.{json,yaml,toml}")
```

**Get a file overview without reading it all**
```
get_file_summary(owner="owner", repo="repo", path="src/large_module.py", preview_lines=30)
```

---

### Code Search

**Search for a function definition**
```
search_code(owner="owner", repo="repo", query="def calculate_total")
```

**Search within a specific file type**
```
search_code(owner="owner", repo="repo", query="import requests", include_pattern="*.py")
```

**Regex search for TODO / FIXME comments**
```
search_code(owner="owner", repo="repo", query="TODO|FIXME|HACK", is_regexp=true)
```

**Search on a non-default branch**
```
search_code(owner="owner", repo="repo", query="feature_flag", ref="feature/new-flags")
```

---

### Git Operations

**List all branches**
```
list_branches(owner="owner", repo="repo")
```

**Get recent commits**
```
get_commits(owner="owner", repo="repo", limit=10)
```

**Get commits on a specific branch**
```
get_commits(owner="owner", repo="repo", ref="develop", limit=20)
```

**Get commits that changed a specific file**
```
get_commits(owner="owner", repo="repo", path="src/auth.py", limit=10)
```

**Compare two branches**
```
get_diff(owner="owner", repo="repo", base="main", head="feature/new-auth")
```

**Compare a commit SHA to HEAD**
```
get_diff(owner="owner", repo="repo", base="abc1234", head="HEAD")
```

**See who last changed each line**
```
get_blame(owner="owner", repo="repo", path="src/server.py", ref="main")
```

**See all commits that touched a file**
```
get_file_history(owner="owner", repo="repo", path="src/auth.py", limit=15)
```

---

### Repository Info

**Get repo metadata**
```
get_repo_info(owner="microsoft", repo="vscode")
```

**View top-level folder structure**
```
get_repo_structure(owner="microsoft", repo="vscode", max_depth=2)
```

**View structure of a sub-folder only**
```
get_repo_structure(owner="microsoft", repo="vscode", path_filter="src/vs/editor/**")
```

**Language breakdown**
```
get_languages(owner="microsoft", repo="vscode")
```

**Check remaining GitHub API quota**
```
get_rate_limit()
```

---

### Write & Code Tools

**Create a branch**
```
create_branch(owner="owner", repo="repo", branch="feature/my-feature")
create_branch(owner="owner", repo="repo", branch="hotfix/x", from_ref="v2.1.0")
```

**Commit files (single or multiple in one commit)**
```
push_files(
    owner="owner", repo="repo", branch="feature/my-feature",
    files=[
        {"path": "src/app.py", "content": "print('hello')"},
        {"path": "tests/test_app.py", "content": "def test_hello(): pass"}
    ],
    message="Add app with tests"
)
```

**Delete a file**
```
delete_file(owner="owner", repo="repo", path="src/old_module.py",
            message="Remove deprecated module", branch="main")
```

**Open a pull request**
```
create_pull_request(owner="owner", repo="repo", title="Add feature X",
                    head="feature/my-feature", base="main",
                    body="Closes #42\n\nAdds the X feature.")
```

**Check CI status**
```
list_workflow_runs(owner="owner", repo="repo", branch="feature/my-feature")
```

**Read CI failure logs**
```
get_workflow_run_logs(owner="owner", repo="repo", run_id=12345678)
```

**Trigger a workflow manually**
```
trigger_workflow(owner="owner", repo="repo", workflow_id="ci.yml", ref="main")
trigger_workflow(owner="owner", repo="repo", workflow_id="deploy.yml",
                 ref="main", inputs={"environment": "production"})
```

**Merge a PR**
```
merge_pull_request(owner="owner", repo="repo", pull_number=7, merge_method="squash")
```

**Create an issue**
```
create_issue(owner="owner", repo="repo", title="Bug: login fails",
             body="Steps to reproduce...", labels=["bug", "priority: high"])
```

---

## Architecture

```
server.py                    ← FastMCP entry point (Streamable HTTP transport); all 26 tools
src/
├── github_client.py         ← Async GitHub REST + GraphQL client (httpx)
├── cache.py                 ← In-memory TTL cache (trees: 5 min, files: 2 min)
├── auth/                    ← Auth providers (token, OAuth, both)
└── tools/
    ├── file_ops.py          ← read_file, list_directory, find_files
    ├── code_search.py       ← search_code, get_file_summary
    ├── git_ops.py           ← list_branches, get_commits, get_diff, get_blame, get_file_history
    ├── repo_info.py         ← get_repo_info, get_repo_structure, get_languages, get_rate_limit
    ├── write_ops.py         ← create_branch, push_files, delete_file, workflow tools
    └── pr_ops.py            ← create/list/get/merge PR, add_pr_comment, create_issue
tests/
├── conftest.py              ← Shared mock_client fixture
└── test_*.py                ← Unit tests per tool module
docs/
├── github-oauth-callback-guide.md   ← Callback URL selection guide
└── oauth-callback-workflows.md      ← OAuth sequence diagrams
```

### Key Design Decisions

| Decision | Reason |
|----------|--------|
| `MCP_READ_ONLY` flag | Lets operators with read-only PATs disable write tools at the registration level — they become invisible to AI agents rather than failing at runtime |
| Write tools use Git Data API for `push_files` | Blob → tree → commit → update ref allows multiple files in one atomic commit, matching how real editors work |
| Write 403 errors include permission hints | When a write call fails due to insufficient PAT scope, the error message lists exactly which fine-grained permissions are needed |
| Server-side PAT for all GitHub calls | Clients never need GitHub permissions themselves; OAuth is identity-only |
| GitHub App (not OAuth App) for OAuth | GitHub Apps support up to 10 callback URLs — one app covers VS Code, Copilot Studio, and any other client |
| Scope normalisation at startup | `GITHUB_OAUTH_SCOPES` child scopes (e.g. `read:user`) are mapped to their GitHub parent (`user`) at parse time. GitHub App tokens return only the parent scope (or nothing); requiring the parent directly means both classic OAuth Apps and GitHub Apps pass the same check without any runtime scope expansion logic. |
| In-memory TTL cache | Reduces GitHub API calls; trees cached 5 min, files 2 min |
| Large file fallback to Blobs API | Files > 1 MB bypass the Contents API size limit automatically |
| Dual search strategy | Simple text → GitHub Search API; regex or branch-specific → local `re` search |
| GraphQL for blame | REST API has no blame endpoint; GraphQL provides full per-line data |

### Rate Limits

| GitHub API | Limit |
|-----------|-------|
| REST API | 5,000 requests / hour |
| Search API | 30 requests / minute |
| GraphQL API | 5,000 points / hour |

Use `get_rate_limit` to check your current status before heavy operations.

---

## Documentation

- [GitHub OAuth Callback Guide](docs/github-oauth-callback-guide.md) — which callback URL to use for Power Automate vs VS Code OAuth
- [OAuth Callback Workflows](docs/oauth-callback-workflows.md) — sequence diagrams for each OAuth flow

> **Note:** All references to "GitHub OAuth App" in older docs should be read as "GitHub App" (the newer type). GitHub Apps are preferred because they support multiple callback URLs.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_file_ops.py

# Run a single test
pytest tests/test_file_ops.py::test_read_file_success

# Lint and format
ruff check .
ruff format .
```

---

## License

MIT
