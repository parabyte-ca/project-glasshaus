# Configuration reference

Every setting a Glasshaus administrator can change, where it lives, and the choices for each.

- **`.env`**: server settings, read when the containers start. `./setup.sh` creates it from
  `.env.example` and fills in the secrets. After editing it, apply the change with
  `docker compose up -d` (or `./update.sh`, which also backs up first).
- **In the app**: settings owners and admins change under **Admin** (and a few per project). They are
  stored in the database, take effect immediately and are included in backups.
- **On the host**: folders, cron jobs and ports outside the containers.

Legend: **Required** must be set (setup.sh does it for you where noted). **Secret** must be kept private
and out of version control. Defaults are what you get when the line is missing or blank.

## Contents

- [Quick start: what you must decide](#quick-start-what-you-must-decide)
- [Server settings (.env)](#server-settings-env)
  - [Release and images](#release-and-images)
  - [Network, ports and URLs](#network-ports-and-urls)
  - [Secrets](#secrets)
  - [First owner and organization](#first-owner-and-organization)
  - [Application and logging](#application-and-logging)
  - [Rate limits](#rate-limits)
  - [MCP server (AI assistants)](#mcp-server-ai-assistants)
  - [Automations and webhooks](#automations-and-webhooks)
  - [AI assistant](#ai-assistant)
  - [Email](#email)
  - [Backups](#backups)
  - [Updates and upgrades](#updates-and-upgrades)
  - [Monitoring](#monitoring)
  - [Advanced (set by Compose; rarely changed)](#advanced-set-by-compose-rarely-changed)
  - [Script options (environment, not .env)](#script-options-environment-not-env)
- [Settings in the app (Admin)](#settings-in-the-app-admin)
- [Installing on a Linux server](#installing-on-a-linux-server)
- [Host-side setup](#host-side-setup)
- [Forgotten password](#forgotten-password)
- [Secrets: what they protect and how to rotate them](#secrets-what-they-protect-and-how-to-rotate-them)

## Quick start: what you must decide

`./setup.sh` produces a working server on `http://<host>:8470` with nothing else set. Before other
people use it, decide these:

| Setting | Why |
| --- | --- |
| `GLASSHAUS_PUBLIC_URL` | The address people type. Links in emails, notifications, calendar feeds and sign-in redirects use it. |
| `GLASSHAUS_ADMIN_EMAIL`, `GLASSHAUS_ADMIN_NAME` | The first owner account (only used on the very first start). |
| `GLASSHAUS_BACKUP_DIR` | Put backups on a different disk or dataset from the database. |
| `GLASSHAUS_BACKUP_KEY` | Generated for you; **copy it to a password manager**. Encrypted backups can't be restored without it. |
| `GLASSHAUS_SMTP_*` | Optional, but needed for any email: scheduled reports, report alerts, assistant digests and system alerts. |
| `GLASSHAUS_UPSTREAM_PROXY` | Only if another reverse proxy (Traefik, Caddy, Nginx Proxy Manager) sits in front. |

## Server settings (.env)

### Release and images

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_VERSION` | the release you installed | `X.Y.Z` | Which release's images run. **Set by `setup.sh` and `update.sh`; don't edit by hand.** |
| `GLASSHAUS_REGISTRY` | `ghcr.io/parabyte-ca` | registry/namespace | Where `update.sh --pull` and `setup.sh --pull` fetch images from. Change only for a fork or a mirror. |
| `GLASSHAUS_BUILD_SHA` | `dev` | git short hash | Shown in About. Set by the scripts. |

### Network, ports and URLs

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_BIND_ADDRESS` | `0.0.0.0` | an interface IP, `0.0.0.0` (all), `127.0.0.1` (this host only) | Host interface for the web and MCP ports. Use `127.0.0.1` when a reverse proxy on the same host is the only way in. |
| `GLASSHAUS_WEB_PORT` | `8470` | any free port | The web app, the REST API under `/api`, `/healthz` and `/readyz`. |
| `GLASSHAUS_API_BIND_ADDRESS` | `127.0.0.1` | as above | Host interface for the direct API port. Keep `127.0.0.1` unless something on another host must reach `/metrics` or the API directly; clients then appear with their own address. |
| `GLASSHAUS_API_PORT` | `8471` | any free port | Direct API port (interactive docs at `/api/docs`, `/metrics`). |
| `GLASSHAUS_MCP_PORT` | `8472` | any free port | MCP server for AI assistants (Claude, Copilot). |
| `GLASSHAUS_PUBLIC_URL` | `http://localhost:8470` | full URL, no trailing `/` | **Set this.** The address people use. Used for links, CORS, push notifications and SSO/OAuth redirects. Use `https://` when a proxy terminates TLS. |
| `GLASSHAUS_SOURCE_URL` | the project's GitHub URL | a URL | Where users can get the source code (AGPL-3.0). Point it at your fork if you run modified code. Also where the daily release check looks (GitHub only). |
| `GLASSHAUS_CORS_ORIGINS` | *(empty)* | comma-separated origins | Extra browser origins allowed to call the API. The web app is same-origin, so usually empty. |
| `GLASSHAUS_UPSTREAM_PROXY` | `127.0.0.1/32` | an IP or CIDR | Your reverse proxy's address, so the web container trusts its `X-Forwarded-For` and the audit log and rate limits see real client addresses. Set it only when another proxy is in front. |
| `GLASSHAUS_TRUSTED_PROXIES` | `web,127.0.0.1,::1` | hostnames, IPs or CIDRs, comma-separated | Proxies the API believes `X-Forwarded-For` from. The default trusts the bundled web container; rarely changed. |

### Secrets

All **generated by `setup.sh`** (and filled in by `update.sh` if missing). Never commit `.env`; it is
created with permissions `600`. See [rotation](#secrets-what-they-protect-and-how-to-rotate-them).

| Variable | Generated | What it protects |
| --- | --- | --- |
| `GLASSHAUS_SECRET_KEY` | 48 random bytes (hex) | Signs the short-lived sign-in tokens, encrypts stored third-party secrets (SSO client secrets, integration credentials) and derives the Web Push key. Must be at least 32 characters in production. |
| `POSTGRES_PASSWORD` | 24 bytes | The database owner role (migrations and backups only). Blanked inside the app containers. |
| `POSTGRES_APP_PASSWORD` | 24 bytes | The least-privilege role the app uses (row-level security enforced). Set on the role by every migrate run. |
| `REDIS_PASSWORD` | 24 bytes | Redis (job queue, live updates, caches). |
| `GLASSHAUS_ADMIN_PASSWORD` | 12 bytes | The first owner's initial password. **Change it after the first sign-in**; editing it later does nothing (see [Forgotten password](#forgotten-password)). |
| `GLASSHAUS_BACKUP_KEY` | an `age` secret key | Encrypts backups. **Keep a copy off the server.** Empty means unencrypted backups. |
| `GLASSHAUS_METRICS_TOKEN` | not generated | Optional bearer token for `/metrics` (see [Monitoring](#monitoring)). |
| `GLASSHAUS_MCP_TOKEN` | not generated | Optional; see [MCP server](#mcp-server-ai-assistants). |
| `GLASSHAUS_AI_API_KEY`, `GLASSHAUS_SMTP_PASSWORD` | not generated | Provider credentials; see their sections. |

### First owner and organization

Used only on the first start, when the organization has no people yet. After that, manage people in
**Admin → People**.

| Variable | Default | What it does |
| --- | --- | --- |
| `GLASSHAUS_ADMIN_EMAIL` | `admin@example.com` | First owner's sign-in email. Also the contact address in Web Push requests. |
| `GLASSHAUS_ADMIN_NAME` | `Administrator` | First owner's display name. |
| `GLASSHAUS_ADMIN_PASSWORD` | generated | See [Secrets](#secrets). |
| `GLASSHAUS_DEFAULT_TENANT_NAME` | `My organization` | Organization name shown in the app. |
| `GLASSHAUS_DEFAULT_TENANT_SLUG` | `default` | Internal short name of the organization. Leave as is. |
| `GLASSHAUS_MULTI_TENANT` | `false` | `true` hosts several separate organizations on one server. Server-wide pages (Backups, Updates, System status) are then hidden from organization admins. Leave `false` for one team or company. |

### Application and logging

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_ENV` | `production` | `production`, `development`, `test` | Keep `production`: it enforces a strong secret key and refuses to start with an unsafe database role. |
| `GLASSHAUS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Log detail. `DEBUG` only while troubleshooting. |
| `GLASSHAUS_LOG_JSON` | `true` | `true`, `false` | JSON logs (for Loki, Graylog…); `false` for readable console output. |
| `GLASSHAUS_API_WORKERS` | `2` | `1`–number of CPU cores | API processes. Each has its own database pool; raise on hosts with spare cores and many users. |

### Rate limits

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_API_RATE_LIMIT_PER_MINUTE` | `1200` | number, `0` = off | REST and SCIM requests per token, session or client address per minute. |
| `GLASSHAUS_MCP_RATE_LIMIT_PER_MINUTE` | `120` | number, `0` = off | MCP tool calls per person per minute. |
| `GLASSHAUS_AI_RATE_LIMIT_PER_MINUTE` | `10` | number, `0` = off | AI requests per person per minute. |

### MCP server (AI assistants)

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_MCP_PUBLIC_URL` | `http://localhost:8472` | URL without `/mcp` | How assistants reach the MCP server. OAuth sign-in for assistants needs `https://` (or localhost); otherwise only personal API tokens work. |
| `GLASSHAUS_MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,mcp:*` | `host:port` patterns, comma-separated | Host names clients may use (protects against DNS rebinding). Add your server's name, e.g. `glasshaus.lan:*`. |
| `GLASSHAUS_MCP_TOKEN` | *(empty)* | a personal API token | Only for `glasshaus-mcp --transport stdio` on the same machine. Not needed for the HTTP MCP server. |

### Automations and webhooks

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE` | `false` | `true`, `false` | `true` lets automations and webhooks call private-network addresses (Home Assistant on `192.168.x.x`, Tailscale `100.x`). Loopback, link-local and cloud metadata addresses are always refused. |
| `GLASSHAUS_WEBHOOK_TIMEOUT_SECONDS` | `10` | seconds | How long a webhook call may take. |

### AI assistant

Off unless a provider is set here **and** an admin turns features on in **Admin → AI**. See
[ai.md](ai.md).

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_AI_PROVIDER` | `none` | `none`, `anthropic` (Claude API), `openai` (any OpenAI-compatible server: Ollama, LM Studio, vLLM, Azure OpenAI), `fake` (canned answers for demos) | Which AI service to use. |
| `GLASSHAUS_AI_MODEL` | `claude-opus-5-5` (anthropic), `llama3.1` (openai) | a model name | Model to use. |
| `GLASSHAUS_AI_API_KEY` | *(empty)* | key | **Secret.** Claude API key (or set `ANTHROPIC_API_KEY`); optional bearer token for `openai`. |
| `GLASSHAUS_AI_BASE_URL` | *(empty)* | URL | `openai` only: e.g. `http://ollama:11434/v1` or `https://<resource>.openai.azure.com/openai/v1`. Leave blank for `anthropic`. |
| `GLASSHAUS_AI_AUTH_HEADER` | `bearer` | `bearer`, `api-key` | `openai` only: `api-key` for Azure OpenAI keys. |
| `GLASSHAUS_AI_API_VERSION` | *(empty)* | e.g. `2024-10-21` | `openai` only: needed for classic Azure URLs (`/openai/deployments/<name>`); blank for `/openai/v1`. |
| `GLASSHAUS_AI_EFFORT` | *(empty)* | *(empty)*, `low`, `medium`, `high` | Claude only: how hard the model thinks. Blank uses the model's default. |
| `GLASSHAUS_AI_FALLBACKS` | `true` | `true`, `false` | Claude only: re-run a declined request on Anthropic's recommended fallback model. |
| `GLASSHAUS_AI_TIMEOUT_SECONDS` | `120` | seconds | Longest wait for one AI answer. |

### Email

Off while `GLASSHAUS_SMTP_HOST` is blank. Used for scheduled report emails, report alerts, assistant
digests and system alerts. See [reports.md](reports.md).

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_SMTP_HOST` | *(empty)* | host name | e.g. `smtp.office365.com`, `smtp.gmail.com`, or a relay on your network. |
| `GLASSHAUS_SMTP_PORT` | `587` | port | Usually `587` (starttls) or `465` (tls); `25` for a local relay. |
| `GLASSHAUS_SMTP_SECURITY` | `starttls` | `starttls`, `tls`, `none` | `none` only for a relay on your own network. |
| `GLASSHAUS_SMTP_USERNAME` | *(empty)* | mailbox | Leave blank for a relay without sign-in. |
| `GLASSHAUS_SMTP_PASSWORD` | *(empty)* | password | **Secret.** Gmail and Office 365 accounts with two-factor need an app password. |
| `GLASSHAUS_SMTP_FROM` | `Glasshaus <glasshaus@localhost>` | `Name <address>` | Sender shown on emails. Must be an address the server may send as. |
| `GLASSHAUS_SMTP_TIMEOUT_SECONDS` | `30` | seconds | Longest wait for the mail server. |

### Backups

The `backup` service saves the database on a schedule and regularly proves a backup restores. See
[Backup and restore](../README.md#backup-and-restore).

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_BACKUP_DIR` | `./backups` | host path | Where backups are written. Put it on a different disk or dataset (and ideally replicate it off-site). |
| `GLASSHAUS_BACKUP_INTERVAL_HOURS` | `24` | hours | Time between backups. |
| `GLASSHAUS_BACKUP_RETENTION_DAYS` | `14` | days | Backups older than this are deleted. |
| `GLASSHAUS_BACKUP_DRILL_DAYS` | `7` | days, `0` = off | How often the newest backup is restored into a scratch database to prove it works. |
| `GLASSHAUS_BACKUP_KEY` | generated | `age` secret key, or empty | **Secret.** Encrypts backups. Empty = unencrypted. |
| `GLASSHAUS_BACKUP_UID`, `GLASSHAUS_BACKUP_GID` | the user who ran `setup.sh` | numeric IDs | Owner of the backup files on the host. Set by `setup.sh`; change if your backup dataset needs a specific owner. |

### Updates and upgrades

See [upgrades.md](upgrades.md).

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_UPDATE_CHECK` | `true` | `true`, `false` | Check GitHub once a day for a new release and notify owners and admins. Only the version and notes come back; nothing about your server is sent. |
| `GLASSHAUS_UPGRADE_FOLDER` | `./upgrade` | host path | Folder shared between the app and the host's upgrade helper, for upgrades started in **Admin → Updates**. |
| `GLASSHAUS_UPGRADE_ARGS` | *(empty)* | `--pull` and/or `--skip-preflight` | Extra `update.sh` options for upgrades started from the app. `--pull` downloads published images instead of building. Anything else is ignored. |

### Monitoring

See [monitoring.md](monitoring.md).

| Variable | Default | Options | What it does |
| --- | --- | --- | --- |
| `GLASSHAUS_METRICS_ENABLED` | `true` | `true`, `false` | Prometheus `/metrics` on the API port. |
| `GLASSHAUS_METRICS_TOKEN` | *(empty)* | a long random string | **Secret.** When set, `/metrics` needs `Authorization: Bearer <token>`. Set it before exposing the API port to another host. |
| `GLASSHAUS_OTEL_ENABLED` | `false` | `true`, `false` | Send OpenTelemetry traces. Configure the destination with the standard `OTEL_EXPORTER_OTLP_ENDPOINT` (and `OTEL_EXPORTER_OTLP_HEADERS`). |
| `GLASSHAUS_OTEL_SERVICE_NAME` | `glasshaus` | name | Service name on traces. |

### Advanced (set by Compose; rarely changed)

`docker-compose.yml` sets these for you. Override them only if you run Glasshaus without the bundled
Compose file.

| Variable | Set to | What it does |
| --- | --- | --- |
| `GLASSHAUS_DATABASE_URL` | the app role on the `postgres` service | Database connection for the API, worker and MCP server. |
| `GLASSHAUS_MIGRATION_DATABASE_URL` | the owner role | Used only by the one-shot migrate job. |
| `GLASSHAUS_DATABASE_POOL_SIZE` | `10` | Connections per process. |
| `GLASSHAUS_REDIS_URL` | the `redis` service | Redis connection. |
| `GLASSHAUS_BACKUP_STATUS_DIR` | `/backups` | The backup folder as seen inside the containers (read-only), for Admin → Backups and the daily check. |
| `GLASSHAUS_UPGRADE_DIR` | `/upgrade` | The upgrade folder as seen inside the API container. |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prometheus` | Shares `/metrics` counters between API processes. |
| `WEB_CONCURRENCY` | `GLASSHAUS_API_WORKERS` | API process count read by uvicorn. |

### Script options (environment, not .env)

Set these in the shell when running a script, e.g. `GLASSHAUS_PREFLIGHT_TIMEOUT=480 sudo -E ./update.sh`.

| Variable | Default | What it does |
| --- | --- | --- |
| `GLASSHAUS_PREFLIGHT_TIMEOUT` | `240` | Seconds `update.sh` waits for the new release to start on a copy of your data. Raise it on slow hosts. |
| `GLASSHAUS_COMPOSE_FILE` | `docker-compose.yml` | Compose file the scripts use (rollback sets this itself). |

`setup.sh` options: `--demo` (sample data), `--pull` (download images instead of building),
`--no-start`. `update.sh` options: `--pull`, `--no-git`, `--version X.Y.Z`, `--rollback-rev REV`,
`--skip-preflight`. `scripts/backup.sh [label]` makes a backup now; `scripts/restore.sh <file> [--yes]`
restores one.

## Settings in the app (Admin)

Open **Admin** (owners and admins only). Every change is recorded in the audit log.

### Roles

| Role | Can |
| --- | --- |
| **Owner** | Everything, including managing other owners and admins, upgrading Glasshaus and reading the upgrade log. Keep at least two. |
| **Admin** | Manage people, sign-in, integrations and organization settings. Can't change or remove owners. |
| **Member** | Work in the projects they belong to. |
| **Guest** | See only the projects they are added to; nothing organization-wide. |

Inside projects: **Admin** (settings, members, assistant), **Editor** (tasks), **Commenter**, **Viewer**.
Workspace roles map to these: workspace admin → project admin, member → editor, viewer → viewer.
Organization owners and admins act as project admins everywhere.

Some actions need a signed-in browser session and refuse API tokens: resetting passwords, making
someone an admin or owner, exporting data, erasing a person and upgrading.

### People

| Setting | Options | Default | Notes |
| --- | --- | --- | --- |
| Add a person: email, name, role | Owner (owners only), Admin, Member, Guest | Member | Name 1–200 characters. |
| Temporary password | 12+ characters, or empty | empty | Leave empty for people who sign in with single sign-on. |
| Role | Owner, Admin, Member, Guest | — | You can't change your own role. Only owners change owners. |
| Deactivate / Reactivate | — | active | Deactivating signs the person out everywhere. |
| Reset password | 12+ characters | — | Signs them out. Not for your own account (use Account). |
| Sign out everywhere | — | — | Ends sessions, API tokens and assistant connections. |
| Download data / Erase | — | — | Personal data export, or permanent anonymisation (type their email to confirm). See [privacy.md](privacy.md). |

**Capacity** (hours a person can work per day, 0–24, default 8) is set by admins on the **Workload**
page.

### Single sign-on

See [sso-scim.md](sso-scim.md). Add one provider per identity system.

| Setting | Options | Default | Notes |
| --- | --- | --- | --- |
| Protocol | OpenID Connect, SAML 2.0 | OpenID Connect | |
| Button label | 1–100 characters | — | Shown on the sign-in page. |
| Short name (in URLs) | lowercase letters, digits, `-` | — | Part of the redirect URI; must be unique. |
| Allowed email domains | comma-separated, up to 50 | empty = any | Restricts who can sign in with this provider. |
| Role for new accounts | Member, Guest, Admin | Member | Accounts are created on first sign-in. |
| OIDC: Issuer URL, Client ID, Client secret | from your identity provider | — | The secret is stored encrypted and never shown again. |
| SAML: IdP entity ID, IdP SSO URL, signing certificate (PEM), email attribute | from your identity provider | email: NameID | |
| Enable / Disable | — | enabled | |
| Require SSO | on, off | off | Everyone except owners must use SSO (owners keep a password as a way back in). |
| Link existing accounts by email | on, off | off | Needs allowed domains. Never links owner or admin accounts. |

Set through the API only: create accounts on first sign-in (on by default), OIDC scopes
(`openid email profile`) and claims (`email`, `name`), the SAML name attribute, and editing a
provider's name, domains, role or identity-provider details after it is created. To change those in
the app, remove the provider and add it again.

### Provisioning

| Setting | Options | Default | Notes |
| --- | --- | --- | --- |
| SCIM token | a name (e.g. "Entra ID") | — | Shown once. Base URL: `<GLASSHAUS_PUBLIC_URL>/scim/v2`. People created by SCIM are Members; SCIM can't change owners or admins. Groups become workspaces. Revoke any time. |
| Managers from Microsoft Entra ID: Directory (tenant) ID, Application (client) ID, Client secret | from an Entra app with the `User.Read.All` application permission | off | Fills in managers, job titles and departments. |
| Sync every night | on, off | off | Needs all three values above. **Sync now** runs it immediately. |
| What managers see on My team | Only in projects the manager can open (counts elsewhere); Their reports' work in every project | Only in projects the manager can open | See [my-team.md](my-team.md). |

### Integrations

See [connectors.md](connectors.md). Each integration can be turned off, tested, and (outbound) shows
its delivery log. Failed deliveries are retried for about five hours.

| Type | You enter | Notes |
| --- | --- | --- |
| Slack, Microsoft Teams | Name, webhook URL, project (or all), events | Also **Scheduled posts**: a saved report or a project's status, daily, weekly or monthly at a set time. |
| Signed webhook | Name, URL, project (or all), events, signing secret (generated if empty) | Private-network URLs need `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE=true`. |
| GitHub, GitLab | Name, project, signing secret (generated if empty) | Inbound: commits and pull/merge requests that mention a task key comment on it; `fixes WEB-12` completes it. |
| Email to task | Name, project, IMAP host (TLS, port 993), username, password, allowed senders (empty = anyone) | The `INBOX` folder; other folders and ports through the API. |
| Slack command (`/glasshaus`) | Name, signing secret, bot token (`xoxb-…`) | Organization-wide. |

Events for outbound integrations: task created, updated, completed, deleted or restored; comment
created; dependency created; project created, updated or imported; time logged; automation failed.
Default: task created, task completed, comment created.

Changing an integration's name, URL, events or credentials is API-only; in the app, remove it and
connect it again.

### AI

Needs `GLASSHAUS_AI_PROVIDER` on the server first. See [ai.md](ai.md).

| Setting | Options | Default |
| --- | --- | --- |
| Turn on the AI assistant for this organization | on, off | off |
| Features | Status updates, Task drafting, Risk flags, Ask in plain words, Questions about reports, Project assistant | the first four |
| What the project assistant may do without approval | Post follow-up comments | nothing (projects can't go beyond this ceiling) |

### Data & retention

| Setting | Options | Default |
| --- | --- | --- |
| Audit log (days) | 0 (forever) or 30–3650 | 365 |
| Activity history (days) | 0 (forever) to 3650 | 730 |
| Notifications (days) | 0 (forever) to 3650 | 90 |
| Deleted tasks, restorable until purged (days) | 0 (forever) to 3650 | 30 (tasks with logged time are kept) |

Ended sign-in sessions are deleted after 90 days (fixed). **Download export** saves the organization's
data (without secrets).

### Pages without settings

- **Audit log**: search, filter and **Check integrity**. Retention is under Data & retention.
- **System status**, **Backups**, **Updates**: single-organization servers only. Their schedules and
  switches are server settings (`GLASSHAUS_BACKUP_*`, `GLASSHAUS_UPDATE_CHECK`). Only owners can press
  **Upgrade**; it needs the [upgrade helper](#host-side-setup).

### Per project (project admins)

| Where | Setting | Options | Default |
| --- | --- | --- | --- |
| Project page → People | Members and their role | Admin, Editor, Commenter, Viewer | Editor |
| Project settings → Custom fields | Name and type | Text, Number, Date, Single select, Multi select, Person, Checkbox, URL | — |
| Timeline | Auto-schedule dependents | on, off | off |
| Project page → Project assistant | Assistant on | on, off | off until a project admin saves the page |
| | Daily digest: send, time, weekdays only | on/off, 00:00–23:59, on/off | on, 08:00, weekdays |
| | Weekly status draft: write, day, hour | on/off, Monday–Sunday, 0–23 | on, Friday, 14:00 |
| | Time zone | any time zone | your browser's |
| | Stale after (days without an update) | 1–60 | 5 |
| | Suggest follow-ups, dates and owners | on, off | on |
| | Post follow-up comments without approval; at most per day | on/off (only if the organization allows it); 1–50 | off; 10 |
| | Deliver by | Notification, Email (needs SMTP), a Slack or Teams channel | Notification |

The assistant's AI write-up also needs the **Project assistant** feature on under Admin → AI. See
[assistant.md](assistant.md).

## Installing on a Linux server

These steps work on any 64-bit Linux server that can run Docker (Debian, Ubuntu, Fedora, RHEL, Rocky,
Alma, openSUSE, Arch and others). Commands that differ by family are shown for both
**Debian/Ubuntu** (`apt`, `ufw`) and **Fedora/RHEL** (`dnf`, `firewalld`).

1. **Install Docker Engine and the Compose plugin**, and start it on boot. Use your distribution's
   instructions at <https://docs.docker.com/engine/install/>, or Docker's script:

   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo systemctl enable --now docker
   docker compose version   # must be 2.20 or later
   ```

   Also install Git: `sudo apt install git` or `sudo dnf install git`.

2. **Create a user to run Glasshaus** (optional but tidy). Membership of the `docker` group is
   equivalent to root, so give it only to this user:

   ```bash
   sudo useradd --create-home --groups docker glasshaus
   sudo mkdir -p /opt/glasshaus && sudo chown glasshaus: /opt/glasshaus
   sudo -iu glasshaus
   ```

3. **Get the code** and prepare the configuration without starting:

   ```bash
   git clone https://github.com/parabyte-ca/project-glasshaus.git /opt/glasshaus
   cd /opt/glasshaus
   ./setup.sh --no-start      # builds images, creates .env with secrets (add --pull to download images)
   ```

4. **Put backups on another disk** (recommended). Mount it (for example at `/srv/glasshaus-backups`
   through `/etc/fstab`), then let the backup service write to it and the app read it:

   ```bash
   sudo mkdir -p /srv/glasshaus-backups
   sudo chown glasshaus: /srv/glasshaus-backups
   sudo setfacl -m u:10001:rx /srv/glasshaus-backups   # the app (uid 10001) reads it; needs the acl package
   ```

   Without ACL support, `sudo chmod 755 /srv/glasshaus-backups` works too: the app only lists the folder;
   the backup files themselves stay readable by the backup service alone.

5. **Edit `.env`**: at least `GLASSHAUS_PUBLIC_URL`, `GLASSHAUS_ADMIN_EMAIL`, `GLASSHAUS_ADMIN_NAME` and
   `GLASSHAUS_BACKUP_DIR=/srv/glasshaus-backups`; add email settings if you have them (see
   [Server settings](#server-settings-env)). Copy `GLASSHAUS_BACKUP_KEY` and `GLASSHAUS_SECRET_KEY` to a
   password manager now.

6. **Start it**:

   ```bash
   ./setup.sh
   grep ^GLASSHAUS_ADMIN_PASSWORD= .env   # first sign-in; change it under Account afterwards
   ```

   Every container restarts on its own after a reboot (`restart: unless-stopped`), as long as Docker
   starts on boot (step 1).

7. **Open the firewall** for the web port (and the MCP port if assistants on other machines connect):

   ```bash
   sudo ufw allow 8470/tcp                                                     # Debian/Ubuntu
   sudo firewall-cmd --permanent --add-port=8470/tcp && sudo firewall-cmd --reload   # Fedora/RHEL
   ```

   Docker publishes ports through its own firewall rules, which `ufw` and `firewalld` zones don't
   filter. To keep a port private, bind it to an address instead: `GLASSHAUS_BIND_ADDRESS=127.0.0.1`
   (only this host) or the server's LAN address.

8. **Add HTTPS** (recommended, and needed for phone notifications and assistant sign-in). With
   [Caddy](https://caddyserver.com/) on the same host, which gets certificates automatically:

   ```text
   # /etc/caddy/Caddyfile
   glasshaus.example.com {
       reverse_proxy 127.0.0.1:8470
   }
   ```

   Then in `.env`: `GLASSHAUS_PUBLIC_URL=https://glasshaus.example.com`,
   `GLASSHAUS_BIND_ADDRESS=127.0.0.1` (so only Caddy reaches Glasshaus) and `GLASSHAUS_UPSTREAM_PROXY`
   set to the address Caddy's connections arrive from. For a proxy on the same host that is the gateway
   of Glasshaus's Docker network:

   ```bash
   docker network inspect glasshaus_frontend -f '{{(index .IPAM.Config 0).Gateway}}'   # e.g. 172.18.0.1
   ```

   Apply with `docker compose up -d`. Any other proxy (Nginx, Traefik, HAProxy) works the same way; it
   must pass WebSocket upgrades for `/api/v1/ws`.

9. **Set up upgrades from the app** (optional): `sudo ./scripts/upgrade-agent.sh --install`. It uses cron
   if installed, otherwise a systemd timer.

10. **Keep a copy of backups elsewhere**: replicate `GLASSHAUS_BACKUP_DIR` to another machine or cloud
    storage (rsync, restic, rclone or your NAS's replication). The backup service only writes locally.

To upgrade later: `cd /opt/glasshaus && sudo ./update.sh` (or **Admin → Updates**).

## Host-side setup

| Item | How | Notes |
| --- | --- | --- |
| Docker and Compose | Docker Engine with Compose v2.20 or later | `setup.sh` checks both. |
| Install folder | Clone the repository; run `./setup.sh` from it | Keep `.env` in this folder (permissions `600`). |
| Ports | `8470` (web), `8471` (API, this host only), `8472` (MCP) | Change in `.env` if taken; `setup.sh` warns about conflicts. Open `8470` (and `8472` if assistants on other machines connect) in the firewall. |
| Backup folder | `GLASSHAUS_BACKUP_DIR`, writable by `GLASSHAUS_BACKUP_UID:GID` | On a NAS, a separate dataset with snapshots and replication. |
| Upgrade helper (optional) | `sudo ./scripts/upgrade-agent.sh --install` | Runs every 15 minutes as root (`--every N` changes it: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30), via `/etc/cron.d` when cron is installed or a systemd timer otherwise. Where the scheduler is managed elsewhere (a NAS web interface), `--print` shows the command to add yourself. `--uninstall` removes it. Only needed to upgrade from **Admin → Updates**. |
| Upgrade folder | Created by `setup.sh`, `update.sh` and the helper | Owned by `10001:10001`, mode `0770`. |
| Start on boot | `sudo systemctl enable docker` | The containers restart themselves once Docker is running. |
| Reverse proxy and TLS (optional) | Point your proxy at `http://<host>:8470` | Set `GLASSHAUS_PUBLIC_URL` to the `https://` address and `GLASSHAUS_UPSTREAM_PROXY` to the proxy's IP. WebSockets (`/api/v1/ws`) must be allowed. For assistants over OAuth, proxy `8472` too and set `GLASSHAUS_MCP_PUBLIC_URL`. |
| Uptime checks (optional) | `http://<host>:8470/readyz` | 200 when the database and Redis are reachable. |
| Prometheus (optional) | Scrape `http://<host>:8471/metrics` | See [monitoring.md](monitoring.md). |
| DNS (optional) | A name for the server | Add it to `GLASSHAUS_MCP_ALLOWED_HOSTS` if assistants use it. |

## Forgotten password

`GLASSHAUS_ADMIN_PASSWORD` in `.env` is only used to create the first owner. After that the password lives
(hashed) in the database, so editing `.env` changes nothing, and a restart doesn't either. Sign in with the
password you set under **Account**, or the one `setup.sh` generated if you never changed it.

If nobody can sign in, set a new one from the server:

```bash
sudo ./scripts/reset-password.sh                    # the GLASSHAUS_ADMIN_EMAIL account
sudo ./scripts/reset-password.sh someone@example.com
```

It asks for the new password (12+ characters, typed twice and not shown), ends that person's other
sign-ins, clears any sign-in lockout from failed attempts and records `user.password_reset` in the audit
log. The stack must be running. Another owner or admin can also reset a password for you under
**Admin → People** (owners only for owners).

## Secrets: what they protect and how to rotate them

Keep a copy of `.env` (or at least `GLASSHAUS_BACKUP_KEY` and `GLASSHAUS_SECRET_KEY`) in a password
manager. Backups contain the database but **not** `.env`.

| Secret | If it leaks | How to rotate | Side effects |
| --- | --- | --- | --- |
| `GLASSHAUS_SECRET_KEY` | Someone could sign in as anyone and read stored integration secrets | Generate a new one (`openssl rand -hex 48`), put it in `.env`, `docker compose up -d` | People stay signed in (their sessions renew) and API tokens keep working. SSO client secrets and integration credentials must be re-entered; push notifications must be turned on again on each device. After a leak, also sign people out (Admin → People) and review the audit log. |
| `POSTGRES_PASSWORD` | Full database access from the Docker network | `docker compose exec postgres psql -U glasshaus -c "ALTER ROLE glasshaus PASSWORD '<new>'"`, then update `.env` and `docker compose up -d` | Changing only `.env` does not change the database. |
| `POSTGRES_APP_PASSWORD` | Database access limited by row-level security | Update `.env`, then `docker compose up -d` (the migrate job sets the new password) | None. |
| `REDIS_PASSWORD` | Read queued jobs and live updates | Update `.env`, then `docker compose up -d` | Queued jobs survive; open browser tabs reconnect. |
| `GLASSHAUS_ADMIN_PASSWORD` | Nothing after the first sign-in (if the password was changed) | Change the password in the app (Account) | Editing `.env` has no effect after the first start. If nobody can sign in, run `sudo ./scripts/reset-password.sh` ([Forgotten password](#forgotten-password)). |
| `GLASSHAUS_BACKUP_KEY` | Someone with your backup files could read them | Generate a new key: `docker compose run --rm --no-deps --entrypoint age-keygen backup`, put the `AGE-SECRET-KEY-…` line in `.env`, `docker compose up -d backup` | **Keep the old key** until every backup made with it has aged out; those backups need it to restore. |
| `GLASSHAUS_METRICS_TOKEN` | Read server metrics | Change in `.env` and in Prometheus; `docker compose up -d api` | None. |
| `GLASSHAUS_SMTP_PASSWORD`, `GLASSHAUS_AI_API_KEY` | Misuse of your mail or AI account | Revoke at the provider, set the new value, `docker compose up -d` | None. |
| Personal API tokens, SCIM tokens | Act as that person or provision people | Revoke in **Account → API tokens** or **Admin → Provisioning**, create a new one | Update the client using it. |
