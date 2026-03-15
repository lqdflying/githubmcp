# GitHub Repo Reader MCP Server

An MCP (Model Context Protocol) server built with **FastMCP** that gives AI agents — such as those in **Copilot Studio** and **VS Code Copilot** — the ability to read and explore GitHub repositories. The server uses a **GitHub Personal Access Token (PAT)** for all GitHub API calls. MCP clients authenticate using a static bearer token, GitHub OAuth, or both.

This server mirrors the same code-reading capabilities available locally in VS Code (file reading, directory listing, grep search, git log, diff, blame, etc.) but operates on remote GitHub repositories via the GitHub API.

---

## Table of Contents

- [Features](#features-14-mcp-tools)
- [How Authentication Works](#how-authentication-works)
- [Prerequisites](#prerequisites)
- [Setup Scenarios](#setup-scenarios)
  - [Scenario 1: Local use with VS Code (simplest)](#scenario-1-local-use-with-vs-code-simplest)
  - [Scenario 2: Remote server with VS Code OAuth](#scenario-2-remote-server-with-vs-code-oauth)
  - [Scenario 3: Remote server with Copilot Studio OAuth](#scenario-3-remote-server-with-copilot-studio-oauth)
  - [Scenario 4: Both VS Code and Copilot Studio (dual auth)](#scenario-4-both-vs-code-and-copilot-studio-dual-auth)
- [Account Access Control](#account-access-control)
- [Creating a GitHub OAuth App](#creating-a-github-oauth-app)
- [Environment Variables](#environment-variables)
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
| 1 | `read_file` | Read a file's contents, optionally a specific line range |
| 2 | `list_directory` | List files and folders inside a directory |
| 3 | `find_files` | Find files matching a glob pattern (e.g. `**/*.py`) |
| 4 | `search_code` | Search for text or regex patterns across all repo files |
| 5 | `get_file_summary` | Get file size, line count, detected language, and a content preview |
| 6 | `list_branches` | List all branches in a repository |
| 7 | `get_commits` | View commit history for a repo or specific file |
| 8 | `get_diff` | Compare two branches, tags, or commits |
| 9 | `get_blame` | See which commit last changed each line of a file |
| 10 | `get_file_history` | List commits that touched a specific file |
| 11 | `get_repo_info` | Get repository metadata (description, stars, topics, etc.) |
| 12 | `get_repo_structure` | View the full folder/file tree of a repository |
| 13 | `get_languages` | See the programming language breakdown |
| 14 | `get_rate_limit` | Check how many GitHub API calls are remaining |

---

## How Authentication Works

There are **two separate authentication layers** — understanding this distinction is important:

```
┌─────────────────────────────────────────────────────┐
│  MCP Client (VS Code / Copilot Studio)              │
│                                                     │
│  "Who are you?" — proved by MCP_API_TOKEN           │
│                   or GitHub OAuth token             │
└──────────────────────────┬──────────────────────────┘
                           │ authenticated MCP call
┌──────────────────────────▼──────────────────────────┐
│  MCP Server (this server)                           │
│                                                     │
│  "Fetch GitHub data" — always uses GITHUB_PAT       │
│  (server's own token, never the client's token)     │
└──────────────────────────┬──────────────────────────┘
                           │ GitHub API requests
┌──────────────────────────▼──────────────────────────┐
│  GitHub API                                         │
└─────────────────────────────────────────────────────┘
```

**Layer 1 — Client → MCP Server:** The client must prove its identity before the server will respond.
**Layer 2 — MCP Server → GitHub:** The server always uses its own `GITHUB_PAT` to fetch data. The client's OAuth token is used for identity only, not for GitHub API access.

This means:
- The GitHub repositories the server can access are controlled entirely by `GITHUB_PAT`
- OAuth restricts *who can call the server*, not *which repos the server can see*
- Even if an OAuth user authenticates, they can only access repos that `GITHUB_PAT` has permission for

### Auth Modes

| Mode | Who can connect | When to use |
|------|----------------|------------|
| `token` | Anyone with `MCP_API_TOKEN` | Local use, trusted environments |
| `oauth` | GitHub users in `ALLOWED_GITHUB_LOGINS` | Remote deployment, identity required |
| `both` | Either token OR GitHub OAuth | Default — supports all clients |

---

## Prerequisites

- **Python 3.12+** (for running directly) or **Docker** (for containerized deployment)
- **GitHub Personal Access Token** with appropriate scopes:
  - **Classic token**: `repo` scope (private + public repos) or `public_repo` (public only)
  - **Fine-grained token**: `Contents: Read` and `Metadata: Read` permissions

### Creating a GitHub PAT

1. Go to **GitHub → Settings → Developer Settings → [Personal Access Tokens](https://github.com/settings/tokens)**
2. Click **"Generate new token (classic)"** or **"Fine-grained tokens"**
3. For classic: check the **`repo`** scope
4. For fine-grained: set **Contents: Read** and **Metadata: Read** under repository permissions
5. Set an expiry date and click **Generate token**
6. **Copy the token immediately** — GitHub only shows it once

---

## Setup Scenarios

### Scenario 1: Local use with VS Code (simplest)

Use this if you're running the server on your own machine and connecting from VS Code on the same machine. No OAuth app needed.

**Step 1 — Clone and install**
```bash
git clone <this-repo-url>
cd githubmcp
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

**Step 2 — Configure .env**
```bash
cp .env.example .env
```

Edit `.env`:
```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=token
MCP_API_TOKEN=your_secret_token_here   # generate: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Step 3 — Start the server**
```bash
python server.py
```

You should see:
```
Authenticated as GitHub user: your-username
```

**Step 4 — Connect VS Code**

Add to `.vscode/mcp.json` (or VS Code `settings.json` under `"mcp"`):
```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer your_secret_token_here"
      }
    }
  }
}
```

Open VS Code Copilot Chat and ask something like:
> "List the branches in microsoft/vscode"

---

### Scenario 2: Remote server with VS Code OAuth

Use this if the server is deployed remotely (e.g. a VPS or cloud VM) and you want to sign in with your GitHub account from VS Code.

**Step 1 — Create a GitHub OAuth App** (see [Creating a GitHub OAuth App](#creating-a-github-oauth-app))

Set the callback URL to: `https://your-server-domain/oauth/callback`

**Step 2 — Configure .env on the server**
```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=oauth
GITHUB_CLIENT_ID=your_oauth_app_client_id
GITHUB_CLIENT_SECRET=your_oauth_app_client_secret
BASE_URL=https://your-server-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

**Step 3 — Deploy and start the server**
```bash
docker compose up -d
```

**Step 4 — Connect VS Code**

Add to `.vscode/mcp.json` — no token needed:
```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "https://your-server-domain/mcp"
    }
  }
}
```

VS Code will detect the OAuth requirement, open a browser window, and ask you to authorize with GitHub. After sign-in it caches the token automatically.

---

### Scenario 3: Remote server with Copilot Studio OAuth

Use this to connect Copilot Studio (Power Automate) to the server with GitHub OAuth.

**Step 1 — Create a GitHub OAuth App** (see [Creating a GitHub OAuth App](#creating-a-github-oauth-app))

Leave the callback URL blank for now — you'll get it from Power Automate in step 4.

**Step 2 — Configure .env on the server**
```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=oauth
GITHUB_CLIENT_ID=your_oauth_app_client_id
GITHUB_CLIENT_SECRET=your_oauth_app_client_secret
BASE_URL=https://your-server-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

**Step 3 — Deploy the server**
```bash
docker compose up -d
```

**Step 4 — Set up Copilot Studio / Power Automate custom connector**

1. In [Power Automate](https://make.powerautomate.com), go to **Custom Connectors → New custom connector → Import from URL**
2. Set the **Host** to your server domain
3. Go to the **Security** tab
4. Set **Authentication type** = `OAuth 2.0`
5. Set **Identity Provider** = `GitHub`
6. Enter your **Client ID** and **Client Secret**
7. Set **Scope** = `read:user`
8. Click **Save** — Power Automate generates a **Redirect URL**
9. Copy that Redirect URL and paste it as the **Authorization callback URL** in your GitHub OAuth App settings
10. Back in Power Automate, click **Test** to create a connection — it will open a GitHub sign-in window

**Step 5 — Add the connector to a Copilot Studio agent**

1. Open your agent in [Copilot Studio](https://copilotstudio.microsoft.com)
2. Go to **Actions → Add an action → Power Automate flow**
3. Select your connector and configure which tools to expose

---

### Scenario 4: Both VS Code and Copilot Studio (dual auth)

Use this to support VS Code with a static token locally AND Copilot Studio with OAuth remotely, both connecting to the same deployed server.

**Step 1 — Create a GitHub OAuth App** (see [Creating a GitHub OAuth App](#creating-a-github-oauth-app))

**Step 2 — Configure .env**
```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=both
MCP_API_TOKEN=your_secret_token_here
GITHUB_CLIENT_ID=your_oauth_app_client_id
GITHUB_CLIENT_SECRET=your_oauth_app_client_secret
BASE_URL=https://your-server-domain
ALLOWED_GITHUB_LOGINS=your-github-username
```

With `MCP_AUTH_MODE=both`:
- VS Code can connect using `Authorization: Bearer your_secret_token_here`
- Copilot Studio connects using GitHub OAuth
- Both go through the same endpoint

---

## Account Access Control

`ALLOWED_GITHUB_LOGINS` controls which GitHub accounts are permitted to sign in via OAuth.

> ⚠️ **If left empty, any valid GitHub account can authenticate.** Always set this when deploying for personal use.

### Allow only your own account
```env
ALLOWED_GITHUB_LOGINS=your-github-username
```

### Allow multiple specific accounts (e.g. you + a colleague)
```env
ALLOWED_GITHUB_LOGINS=your-github-username,colleague-username,another-user
```

The list is comma-separated and case-insensitive. All listed accounts get equal access to all 14 tools.

### How the check works

When a GitHub OAuth token arrives, the server calls GitHub to verify the token and retrieves the authenticated user's login. If that login is not in `ALLOWED_GITHUB_LOGINS`, the request is rejected with a 401. The audit log shows:

```
AUTH success method=oauth login=your-github-username
AUTH rejected method=oauth login=some-other-user reason=login_not_allowlisted
```

> **Note:** `ALLOWED_GITHUB_LOGINS` only affects OAuth logins. Static token auth (`MCP_API_TOKEN`) is not affected by this list.

---

## Creating a GitHub OAuth App

You need a GitHub OAuth App to enable GitHub sign-in for this server.

1. Go to **GitHub → Settings → Developer Settings → [OAuth Apps](https://github.com/settings/developers)**
2. Click **"New OAuth App"**
3. Fill in the form:
   - **Application name**: e.g. `My GitHub MCP Server`
   - **Homepage URL**: your server URL, e.g. `https://your-server-domain`
   - **Authorization callback URL**: depends on your setup (see below)
4. Click **Register application**
5. On the next page, note your **Client ID**
6. Click **"Generate a new client secret"** and copy it immediately

### Which callback URL to use

| Integration | Callback URL |
|-------------|-------------|
| VS Code (native MCP OAuth) | `https://your-server-domain/oauth/callback` |
| Power Automate / Copilot Studio | The Redirect URL generated by Power Automate (get it from the connector Security tab after saving) |

> If you need both VS Code and Power Automate OAuth at the same time, create **two separate GitHub OAuth Apps** — one per callback URL.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_PAT` | **Yes** | — | GitHub Personal Access Token used for all GitHub API calls |
| `MCP_AUTH_MODE` | No | `both` | Auth mode: `token`, `oauth`, or `both` |
| `MCP_AUTH_AUDIT_LOG` | No | `true` | Log auth decisions (never logs token values) |
| `MCP_API_TOKEN` | Conditional | — | Required when `MCP_AUTH_MODE=token` or `both`. Static bearer token for clients. |
| `GITHUB_CLIENT_ID` | Conditional | — | Required when OAuth is enabled |
| `GITHUB_CLIENT_SECRET` | Conditional | — | Required when OAuth is enabled |
| `BASE_URL` | Conditional | — | Public HTTPS URL of this server, e.g. `https://your-server-domain`. Required when OAuth is enabled. |
| `GITHUB_OAUTH_SCOPES` | No | `read:user` | OAuth scopes to request. `read:user` is sufficient for identity verification. |
| `ALLOWED_GITHUB_LOGINS` | **Strongly recommended** | *(empty = allow all)* | Comma-separated GitHub usernames allowed for OAuth. **If empty, any GitHub account can authenticate.** |
| `HOST` | No | `0.0.0.0` | Host interface to bind to |
| `PORT` | No | `8000` | Port to listen on |

> ⚠️ The server exits at startup if `GITHUB_PAT` is missing or invalid.

---

## Docker Deployment

### 1. Prepare environment file

```bash
cp .env.example .env
# Fill in GITHUB_PAT, MCP_API_TOKEN, and optionally OAuth vars
```

Example `.env` for dual auth:
```env
GITHUB_PAT=ghp_your_token_here
MCP_AUTH_MODE=both
MCP_AUTH_AUDIT_LOG=true
MCP_API_TOKEN=your_secret_mcp_token_here
GITHUB_CLIENT_ID=your_oauth_client_id
GITHUB_CLIENT_SECRET=your_oauth_client_secret
BASE_URL=https://your-server-domain
GITHUB_OAUTH_SCOPES=read:user
ALLOWED_GITHUB_LOGINS=your-github-username
HOST=0.0.0.0
PORT=8000
```

Generate a secure `MCP_API_TOKEN`:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Start with Docker Compose

```bash
docker compose up -d
```

```bash
docker compose down        # stop
docker compose logs -f     # view logs
```

### 3. Build locally (optional)

```bash
docker build -t github-repo-reader-mcp .
```

---

## Nginx Reverse Proxy

Sample config to expose the server over HTTPS at your domain. Required for OAuth (GitHub only allows HTTPS callback URLs in production).

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name your-server-domain;
    return 301 https://$host$request_uri;
}

# HTTPS reverse proxy
server {
    listen 443 ssl http2;
    server_name your-server-domain;

    ssl_certificate     /etc/nginx/cert/your-server-domain.crt;
    ssl_certificate_key /etc/nginx/cert/your-server-domain.key;

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

        # Required for SSE streaming (MCP uses long-lived HTTP connections)
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

> Replace `your-server-domain` with your actual domain and update the certificate paths.

---

## VS Code Integration

### Option A: Static Token (local or trusted network)

Best for running the server locally on the same machine as VS Code.

Add to `.vscode/mcp.json` in your project, or to VS Code `settings.json` under `"mcp"`:

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

Requires `MCP_AUTH_MODE=token` or `MCP_AUTH_MODE=both` and `MCP_API_TOKEN` set in your `.env`.

### Option B: GitHub OAuth (remote server)

Best for a server deployed remotely. VS Code will prompt you to sign in with GitHub automatically.

```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "https://your-server-domain/mcp"
    }
  }
}
```

No `Authorization` header is set. VS Code sends an unauthenticated request, receives a `401` with OAuth discovery metadata from FastMCP, then opens the GitHub authorization page in your browser. After you approve, VS Code caches the token for all subsequent calls.

Requires `MCP_AUTH_MODE=oauth` or `MCP_AUTH_MODE=both` and all three OAuth env vars set.

> Set `ALLOWED_GITHUB_LOGINS=your-github-username` to ensure only your account can sign in.

### Using in VS Code Copilot Chat

Once connected, open **Copilot Chat** (`Ctrl+Shift+I` / `Cmd+Shift+I`) and switch to **Agent mode**. You can ask questions like:

```
What files are in the src/ directory of owner/repo?
Show me the last 10 commits on the main branch of owner/repo
Search for all TODO comments in owner/repo
What languages does microsoft/vscode use?
Show me the diff between main and develop in owner/repo
Who last modified line 42 in src/server.py in owner/repo?
```

---

## Copilot Studio Integration

### Option A: Static Token (simple)

If you just need Copilot Studio to call the MCP server without OAuth:

1. In [Copilot Studio](https://copilotstudio.microsoft.com), open your agent
2. Go to **Actions → Add an action → Model Context Protocol**
3. Set the **Server URL** to `https://your-server-domain/mcp`
4. Add a header: `Authorization: Bearer your_secret_mcp_token_here`
5. Publish the agent

### Option B: GitHub OAuth via Power Automate Custom Connector

This is the recommended approach for production — users sign in with their GitHub accounts.

**Prerequisites:** Complete [Scenario 3](#scenario-3-remote-server-with-copilot-studio-oauth) server setup first.

**Step 1 — Create the custom connector in Power Automate**

1. Go to [Power Automate](https://make.powerautomate.com) → **Custom Connectors → New custom connector → Create from blank**
2. Name it (e.g. `GitHub MCP Server`)
3. On the **General** tab, set:
   - **Scheme**: `HTTPS`
   - **Host**: `your-server-domain`
   - **Base URL**: `/`

**Step 2 — Configure security**

1. Go to the **Security** tab
2. Set **Authentication type** = `OAuth 2.0`
3. Set **Identity Provider** = `Generic OAuth 2`
4. Fill in:
   - **Authorization URL**: `https://github.com/login/oauth/authorize`
   - **Token URL**: `https://github.com/login/oauth/access_token`
   - **Client ID**: your GitHub OAuth App client ID
   - **Client Secret**: your GitHub OAuth App client secret
   - **Scope**: `read:user`
   - **Refresh URL**: `https://github.com/login/oauth/access_token`
5. Click **Update connector** — Power Automate generates a **Redirect URL**
6. Copy that Redirect URL and paste it into your [GitHub OAuth App settings](https://github.com/settings/developers) as the **Authorization callback URL**

**Step 3 — Define actions (MCP tools)**

On the **Definition** tab, add actions for each MCP tool you want available. For example, for `read_file`:
- **Operation ID**: `read_file`
- **Verb**: `POST`
- **URL**: `/mcp`
- Body should follow the MCP JSON-RPC format

> Tip: You can also use the MCP connector in Power Automate flows directly to call tools programmatically.

**Step 4 — Create a connection and test**

1. Go to **Test → New connection**
2. Sign in with your GitHub account — only accounts in `ALLOWED_GITHUB_LOGINS` will succeed
3. Run a test action

**Step 5 — Add to Copilot Studio agent**

1. In Copilot Studio → **Actions → Add an action → Power Automate flow**
2. Create a flow that calls your custom connector
3. Map the flow parameters to topics or use the flow directly in generative answers

### Example prompts in Copilot Studio

Once connected, users can ask the agent:
```
What is the folder structure of the repo owner/repo?
Find all Python files in owner/repo
Show me recent commits in owner/repo
What does the file src/main.py do in owner/repo?
Search for the function calculateTotal in owner/repo
```

---

## Tool Reference & Examples

All tools take `owner` (GitHub username or org) and `repo` (repository name) as their first two arguments.

### File Operations

**Read a file**
```
read_file(owner="microsoft", repo="vscode", path="package.json")
```

**Read specific lines only**
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

**Find all config files**
```
find_files(owner="owner", repo="repo", pattern="*.{json,yaml,toml}")
```

### Code Search

**Search for a function definition**
```
search_code(owner="owner", repo="repo", query="def calculate_total")
```

**Search only in Python files**
```
search_code(owner="owner", repo="repo", query="import requests", include_pattern="*.py")
```

**Regex search for TODO comments**
```
search_code(owner="owner", repo="repo", query="TODO|FIXME|HACK", is_regexp=true)
```

**Search on a specific branch**
```
search_code(owner="owner", repo="repo", query="feature_flag", ref="feature/new-flags")
```

**Get a file overview without reading the whole file**
```
get_file_summary(owner="owner", repo="repo", path="src/large_module.py", preview_lines=30)
```

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

**Compare a commit to HEAD**
```
get_diff(owner="owner", repo="repo", base="abc1234", head="HEAD")
```

**See who last changed each line of a file**
```
get_blame(owner="owner", repo="repo", path="src/server.py", ref="main")
```

**See all commits that touched a file**
```
get_file_history(owner="owner", repo="repo", path="src/auth.py", limit=15)
```

### Repository Information

**Get repo metadata**
```
get_repo_info(owner="microsoft", repo="vscode")
```

**View top-level folder structure**
```
get_repo_structure(owner="microsoft", repo="vscode", max_depth=2)
```

**View structure of a sub-folder**
```
get_repo_structure(owner="microsoft", repo="vscode", path_filter="src/vs/editor/**")
```

**Get language breakdown**
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
├── cache.py                 ← In-memory TTL cache (tree: 5 min, files: 2 min)
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

- **Read-only**: No write operations — safe to expose to AI agents
- **Caching**: Repo trees cached 5 min, files 2 min — reduces GitHub API calls
- **Large file fallback**: Files > 1 MB use the Git Blobs API automatically
- **Dual search strategy**: Simple text queries use GitHub Search API; regex or branch-specific searches fetch files and search locally with Python `re`
- **GraphQL for blame**: The REST API has no blame endpoint; GraphQL provides full per-line blame data
- **Rate limit tracking**: Every API response updates the remaining quota counter

### Rate Limits

| API | Limit |
|-----|-------|
| REST API | 5,000 requests/hour |
| Search API | 30 requests/minute |
| GraphQL API | 5,000 points/hour |

Use `get_rate_limit` to check current status before heavy operations.

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

# Lint and auto-fix
ruff check .
ruff format .
```

---

## Documentation

- [GitHub OAuth Callback Guide](docs/github-oauth-callback-guide.md) — which callback URL to use for Power Automate vs native MCP OAuth
- [OAuth Callback Workflows](docs/oauth-callback-workflows.md) — sequence diagrams for each OAuth flow

---

## License

MIT
