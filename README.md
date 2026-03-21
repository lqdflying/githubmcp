# GitHub Repo Reader MCP Server

An MCP (Model Context Protocol) server built with **FastMCP** that gives AI agents — such as **VS Code Copilot** and **Copilot Studio** — the ability to read and explore GitHub repositories. The server uses your **GitHub Personal Access Token (PAT)** for all GitHub API calls. MCP clients authenticate using a static bearer token, GitHub OAuth, or both.

---

## Table of Contents

- [Features](#features-14-mcp-tools)
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

## Features (14 MCP Tools)

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

  | Token type | Required permissions |
  |-----------|---------------------|
  | Classic token | `repo` scope (private + public), or `public_repo` (public only) |
  | Fine-grained token | `Contents: Read` + `Metadata: Read` |

### Creating a GitHub PAT

1. Go to **[GitHub Settings → Developer Settings → Personal Access Tokens](https://github.com/settings/tokens)**
2. Click **Generate new token (classic)** or **Fine-grained tokens → Generate new token**
3. For classic: tick the **`repo`** scope
4. For fine-grained: set **Contents: Read** and **Metadata: Read** under repository permissions
5. Set an expiry and click **Generate token**
6. **Copy the token immediately** — GitHub only shows it once

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

All listed accounts receive identical access to all 14 tools. The check is case-insensitive.

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
| `HOST` | No | `0.0.0.0` | Network interface to bind to |
| `PORT` | No | `8000` | Port to listen on |

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
5. Copilot Studio will discover all 14 tools automatically — select the ones you want to expose
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

## Architecture

```
server.py                    ← FastMCP entry point (Streamable HTTP transport)
src/
├── github_client.py         ← Async GitHub REST + GraphQL client (httpx)
├── cache.py                 ← In-memory TTL cache (trees: 5 min, files: 2 min)
└── tools/
    ├── file_ops.py          ← read_file, list_directory, find_files
    ├── code_search.py       ← search_code, get_file_summary
    ├── git_ops.py           ← list_branches, get_commits, get_diff, get_blame, get_file_history
    └── repo_info.py         ← get_repo_info, get_repo_structure, get_languages, get_rate_limit
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
| Read-only — no write tools | Safe to expose to AI agents without risk of data modification |
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
