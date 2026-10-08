# Connecting AI assistants (MCP)

Project Glasshaus runs a Model Context Protocol server in its own container (`mcp`, port **8472**,
endpoint `/mcp`, Streamable HTTP). It exposes the same capabilities as the REST API through the same
service layer, so permissions are identical: an assistant can only see and change what you can, limited
further by the scopes you grant it. See [the coverage matrix](../coverage-matrix.md) for every tool.

Every file in this folder is checked by `backend/tests/test_integrations.py`; the HTTP flows they rely on
are exercised by the conformance suite in `backend/tests/test_mcp_conformance.py`.

## Choose how the assistant signs in

| Method | When | How |
| --- | --- | --- |
| **OAuth 2.1** (recommended) | The MCP server is reached over **HTTPS**, or on `localhost` | The client discovers everything from `/mcp`: it registers itself (dynamic client registration), sends you to the Glasshaus consent page, and gets short-lived tokens (PKCE, rotating refresh tokens). Manage or disconnect apps under **Account → Connected apps**. |
| **API token** | Plain HTTP on your LAN, scripts, CI | Create one under **Account → API tokens** and send `Authorization: Bearer ghp_…`. |

OAuth needs an HTTPS issuer. Put the MCP port behind your reverse proxy (Caddy, Traefik, nginx) and set
in `.env`:

```dotenv
GLASSHAUS_MCP_PUBLIC_URL=https://mcp.glasshaus.example.com   # what clients use, without /mcp
GLASSHAUS_MCP_ALLOWED_HOSTS=mcp.glasshaus.example.com,localhost:*,127.0.0.1:*,mcp:*
GLASSHAUS_PUBLIC_URL=https://glasshaus.example.com           # the web app (consent page)
```

Over plain HTTP on a non-localhost address the server accepts API tokens only.

Scopes: `read` (everything you can see), `tasks:write` (tasks, comments, dependencies, time),
`projects:write` (projects, automations, goals, settings), `admin` (organization administration and the
audit log; admins only).

## Safety

- **Destructive tools preview first.** `delete_tasks`, `delete_project`, `bulk_update_tasks`,
  `reschedule_project` and deletes inside `manage_*` tools return a dry-run preview unless called with
  `confirm=true`. Tools carry MCP `destructiveHint`/`readOnlyHint` annotations so clients can ask you first.
- **Content is untrusted.** Titles, descriptions and comments are returned as data, and tool descriptions
  tell the model never to follow instructions found in them. The server never calls tools on its own.
- **Audited.** Every tool call is logged with the user, client, arguments (secrets redacted), outcome and
  duration: `GET /api/v1/audit-log` or the `get_audit_log` tool (organization admins).
- **Rate limited** per user: `GLASSHAUS_MCP_RATE_LIMIT_PER_MINUTE` (default 120).

## GitHub Copilot in VS Code (agent mode)

Put [`vscode/mcp.json`](vscode/mcp.json) in `.vscode/mcp.json` (or your user `mcp.json`) and change the
URL. VS Code finds the OAuth metadata, opens the consent page, then lists the tools in agent mode.

Without HTTPS, use [`vscode/mcp.token.json`](vscode/mcp.token.json): VS Code prompts for the API token
once and stores it securely.

Try: *"Create a task 'Draft launch post' in WEB, make WEB-3 wait for it, then give me the status summary."*

## Claude Code

```bash
claude mcp add --transport http glasshaus https://mcp.glasshaus.example.com/mcp           # OAuth
claude mcp add --transport http glasshaus http://glasshaus.lan:8472/mcp \
  --header "Authorization: Bearer $GLASSHAUS_TOKEN"                                     # API token
```

Or commit [`claude/mcp.json`](claude/mcp.json) as `.mcp.json` in a project; it reads `GLASSHAUS_TOKEN`
and `GLASSHAUS_MCP_URL` from the environment.

## Claude Desktop

- **HTTPS + OAuth:** Settings → Connectors → Add custom connector → `https://mcp.glasshaus.example.com/mcp`.
- **API token:** merge [`claude/claude_desktop_config.json`](claude/claude_desktop_config.json) into
  `claude_desktop_config.json` (it bridges to HTTP with `mcp-remote`; Node.js required).
- **Same machine as the stack (stdio):** [`claude/claude_desktop_stdio.json`](claude/claude_desktop_stdio.json)
  runs `glasshaus-mcp --transport stdio` in a one-off container; set `--project-directory` to your
  install folder.

## Microsoft Copilot Studio

Preferred: **Tools → Add a tool → New tool → Model Context Protocol**, server URL
`https://mcp.glasshaus.example.com/mcp`, authentication **OAuth 2.0 → Dynamic discovery**. Copilot Studio
registers itself and users approve access on the Glasshaus consent page.

If your tenant requires a custom connector, import
[`copilot-studio/glasshaus-mcp-connector.yaml`](copilot-studio/glasshaus-mcp-connector.yaml) in Power
Apps (it marks `POST /mcp` with `x-ms-agentic-protocol: mcp-streamable-1.0`). Set the host, and enter
`Bearer ghp_…` as the API key when creating the connection.

## Microsoft 365 Copilot (declarative agent)

[`m365/`](m365) holds a declarative agent with two interchangeable actions:

- [`glasshaus-mcp-plugin.json`](m365/glasshaus-mcp-plugin.json): a `RemoteMCPServer` runtime with
  dynamic tool discovery. Register an OAuth client in the Teams Developer Portal (the authorization,
  token and registration URLs are in `https://mcp.glasshaus.example.com/.well-known/oauth-authorization-server`)
  and use its ID as `GLASSHAUS_OAUTH_REFERENCE_ID`.
- [`glasshaus-api-plugin.json`](m365/glasshaus-api-plugin.json) + [`openapi.json`](m365/openapi.json):
  the REST fallback (OpenAPI 3.0, generated from the main API by `make openapi`). Register an API key
  (`Bearer ghp_…`) in the Developer Portal as `GLASSHAUS_APIKEY_REFERENCE_ID`, and set `servers[0].url`.

The agent references the MCP plugin; point `actions[0].file` at `glasshaus-api-plugin.json` to use the
REST fallback. Package and sideload with the Microsoft 365 Agents Toolkit.

## Any other MCP client

- Endpoint: `POST/GET/DELETE {base}/mcp` (Streamable HTTP). Health: `GET {base}/healthz`.
- Discovery: `{base}/.well-known/oauth-protected-resource/mcp` (RFC 9728) and
  `{base}/.well-known/oauth-authorization-server` (RFC 8414); a `401` carries
  `WWW-Authenticate: Bearer resource_metadata="…"`.
- OAuth: `/register` (RFC 7591, public clients use `token_endpoint_auth_method=none`), `/authorize`
  (S256 PKCE required), `/token`, `/revoke`. Access tokens last 1 hour; refresh tokens 30 days and rotate
  on every use (reuse revokes the grant).
- Resources: `glasshaus://projects`, `glasshaus://projects/{key}`, `…/{key}/report`, `…/{key}/status`,
  `glasshaus://tasks/{ref}`, `glasshaus://views/{view_id}`, `glasshaus://dashboards/{dashboard_id}`.
- Prompts: `weekly_status`, `risk_review`, `sprint_planning`, `standup_digest`.

[`examples/agent.py`](../../examples/agent.py) is a complete scripted client: it creates two tasks,
links them and prints the status-summary data.
