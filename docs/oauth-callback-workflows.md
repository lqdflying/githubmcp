# OAuth Callback Workflows

This document shows two callback patterns:

1. Power Automate custom connector OAuth flow (Power Automate owns callback)
2. Native MCP server OAuth flow (server owns callback)

## Workflow 1: Power Automate Owns the Callback URL

In this model, GitHub redirects back to Power Automate. The MCP server only receives bearer tokens on tool calls.

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant PA as Power Automate
    participant GH as GitHub OAuth
    participant MCP as MCP Server

    U->>PA: Create/authorize connector connection
    PA->>GH: Redirect user to GitHub authorize endpoint
    GH-->>U: Login + consent prompt
    U->>GH: Approve requested scopes
    GH->>PA: Redirect to Power Automate callback URL with code
    PA->>GH: Exchange code for access token
    GH-->>PA: Access token
    PA->>MCP: MCP request with Authorization: Bearer <github_token>
    MCP->>GH: Verify token (GitHub API)
    GH-->>MCP: Token valid + user claims
    MCP-->>PA: MCP response
```

### Callback URL used

- Power Automate generated Redirect URL (from connector Security tab after Save/Update)

### Notes

- GitHub callback never returns to MCP server in this flow.
- MCP server still validates incoming GitHub bearer token.

## Workflow 2: Native MCP Server OAuth Callback

In this model, the MCP server hosts OAuth routes and receives callback directly.

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP Client
    participant MCP as MCP Server (OAuth Provider)
    participant GH as GitHub OAuth

    C->>MCP: Start OAuth authorization
    MCP->>GH: Redirect to GitHub authorize endpoint
    GH-->>C: Login + consent prompt
    C->>GH: Approve requested scopes
    GH->>MCP: Redirect to /auth/callback with code
    MCP->>GH: Exchange code for access token
    GH-->>MCP: Access token
    MCP->>GH: Verify token and fetch user claims
    GH-->>MCP: Valid token + user info
    MCP-->>C: Authorized session/token for MCP calls
    C->>MCP: MCP request with bearer token
    MCP-->>C: MCP response
```

### Callback URL used

- https://your-domain/auth/callback

### Notes

- The MCP server owns authorization and callback handling in this flow.
- Use this when clients authenticate directly against MCP OAuth endpoints.

## Choosing Between the Two

- Use Power Automate callback flow when Power Automate custom connector is the primary integration.
- Use native MCP callback flow when your clients authenticate directly with MCP OAuth endpoints.
- If both are needed simultaneously, create separate GitHub OAuth apps (one callback URL each).
