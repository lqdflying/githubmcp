# GitHub Repo Reader MCP Server

An MCP (Model Context Protocol) server built with **FastMCP** that gives AI agents — such as those in **Copilot Studio** — the ability to read and explore GitHub repositories. Authenticates via **GitHub Personal Access Token (PAT)**.

This server mirrors the same code-reading capabilities available locally in VS Code (file reading, directory listing, grep search, git log, diff, blame, etc.) but operates on remote GitHub repositories via the GitHub API.

---

## Features (14 MCP Tools)

| # | Tool | Description |
|---|------|-------------|
| 1 | `read_file` | Read file contents with optional line range |
| 2 | `list_directory` | List directory contents |
| 3 | `find_files` | Search files by glob pattern (e.g. `**/*.py`) |
| 4 | `search_code` | Text/regex search across repo files |
| 5 | `get_file_summary` | File overview: size, line count, language, preview |
| 6 | `list_branches` | List all branches |
| 7 | `get_commits` | View commit history |
| 8 | `get_diff` | Compare two refs (branches/tags/SHAs) |
| 9 | `get_blame` | Git blame via GraphQL API |
| 10 | `get_file_history` | Commits that touched a specific file |
| 11 | `get_repo_info` | Repository metadata |
| 12 | `get_repo_structure` | Full repo tree view |
| 13 | `get_languages` | Language breakdown |
| 14 | `get_rate_limit` | Check GitHub API rate limit status |

---

## Prerequisites

- **Python 3.12+**
- **GitHub Personal Access Token** with appropriate scopes:
  - **Classic tokens**: `repo` scope (for private repos) or `public_repo` (public only)
  - **Fine-grained tokens**: `Contents: Read` and `Metadata: Read` permissions

### Creating a GitHub PAT

1. Go to [GitHub Settings → Developer Settings → Personal Access Tokens](https://github.com/settings/tokens)
2. Click **"Generate new token"** (classic) or **"Generate new token (Beta)"** (fine-grained)
3. For classic tokens: select the `repo` scope
4. For fine-grained tokens: select `Contents: Read` and `Metadata: Read`
5. Copy the token — you won't be able to see it again

---

## Quick Start

### 1. Clone & Install

```bash
git clone <this-repo-url>
cd githubmcp

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and set your GITHUB_PAT and MCP_API_TOKEN

# Generate a secure MCP API token:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Run the Server

```bash
python server.py
```

The server starts on `http://0.0.0.0:8000` with Streamable HTTP transport.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_PAT` | **Yes** | GitHub Personal Access Token for API authentication |
| `MCP_API_TOKEN` | No | Secret token to secure the MCP endpoint (recommended for production) |
| `HOST` | No | Host to bind to (default: `0.0.0.0`) |
| `PORT` | No | Port to listen on (default: `8000`) |

> ⚠️ The server will **fail to start** if `GITHUB_PAT` is not set.

---

## Docker

### 1. Prepare your environment file

```bash
cp .env.example .env
# Edit .env and fill in your GITHUB_PAT and MCP_API_TOKEN
```

`.env` file:
```env
GITHUB_PAT=ghp_your_token_here
MCP_API_TOKEN=your_secret_mcp_token_here
HOST=0.0.0.0
PORT=8000
```

> Generate a secure `MCP_API_TOKEN` with:
> ```bash
> python3 -c "import secrets; print(secrets.token_urlsafe(32))"
> ```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

To stop:
```bash
docker compose down
```

### Build locally (optional)

```bash
docker build -t github-repo-reader-mcp .
```

---

## Nginx Reverse Proxy

Sample config to expose the server via HTTPS at your domain:

```nginx
# HTTP: Redirect all traffic to HTTPS
server {
    listen 80;
    server_name githubmcp.example.com;
    return 301 https://$host$request_uri;
}

# HTTPS: Reverse proxy to github-mcp container
server {
    listen 443 ssl http2;
    server_name githubmcp.example.com;

    ssl_certificate     /etc/nginx/cert/githubmcp.example.com.crt;
    ssl_certificate_key /etc/nginx/cert/githubmcp.example.com.key;

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

        # WebSocket + SSE streaming support
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

> Replace `githubmcp.example.com` with your actual domain and update the certificate paths accordingly.

---

## Copilot Studio Integration

Configure your Copilot Studio agent to connect to this MCP server:

1. In Copilot Studio, go to **Actions** → **Add an action** → **MCP Server**
2. Set the **Server URL** to your deployed endpoint (e.g. `https://your-host:8000/mcp`)
3. The server will expose all 14 tools for the agent to use

### Example Copilot Studio Configuration

```json
{
  "mcpServers": {
    "github-repo-reader": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer your_secret_mcp_token_here"
      }
    }
  }
}
```

---

## VS Code Integration

Add to your VS Code `settings.json` or `.vscode/mcp.json`:

```json
{
  "servers": {
    "github-repo-reader": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MCP_API_TOKEN}"
      }
    }
  }
}
```

---

## Tool Examples

### Read a file
```
read_file(owner="microsoft", repo="vscode", path="package.json")
```

### Read specific lines
```
read_file(owner="microsoft", repo="vscode", path="src/main.ts", start_line=1, end_line=50)
```

### List directory
```
list_directory(owner="microsoft", repo="vscode", path="src")
```

### Find Python files
```
find_files(owner="owner", repo="repo", pattern="**/*.py")
```

### Search for a function
```
search_code(owner="owner", repo="repo", query="def main", include_pattern="*.py")
```

### Regex search
```
search_code(owner="owner", repo="repo", query="import\\s+os", is_regexp=true)
```

### View commit history
```
get_commits(owner="owner", repo="repo", limit=10)
```

### Compare branches
```
get_diff(owner="owner", repo="repo", base="main", head="feature-branch")
```

### Git blame
```
get_blame(owner="owner", repo="repo", path="src/main.py", ref="main")
```

### Repository overview
```
get_repo_info(owner="microsoft", repo="vscode")
get_repo_structure(owner="microsoft", repo="vscode", max_depth=2)
get_languages(owner="microsoft", repo="vscode")
```

---

## Architecture

```
server.py                    ← FastMCP entry point (Streamable HTTP)
src/
├── github_client.py         ← Async GitHub REST + GraphQL client
├── cache.py                 ← In-memory TTL cache
└── tools/
    ├── file_ops.py          ← read_file, list_directory, find_files
    ├── code_search.py       ← search_code, get_file_summary
    ├── git_ops.py           ← list_branches, get_commits, get_diff, get_blame, get_file_history
    └── repo_info.py         ← get_repo_info, get_repo_structure, get_languages
```

### Key Design Decisions

- **Read-only**: No write operations — safe for production use
- **Caching**: Repo trees cached for 5 min, files for 2 min — reduces API calls
- **Fallback**: Files > 1MB automatically use Git Blobs API instead of Contents API
- **Dual search**: Simple queries use GitHub Search API; regex/branch-specific queries search locally
- **GraphQL for blame**: REST API has no blame endpoint; GraphQL provides full blame data
- **Rate limit aware**: Tracks remaining quota from API response headers

### Rate Limits

- **REST API**: 5,000 requests/hour (authenticated)
- **Search API**: 30 requests/minute (authenticated)
- **GraphQL API**: 5,000 points/hour (authenticated)

Use `get_rate_limit` tool to check current status.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Lint
ruff check .
ruff format .
```

---

## License

MIT
