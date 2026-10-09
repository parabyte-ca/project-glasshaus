# Architecture

## Principles

1. **One service layer.** REST routes, MCP tools, webhooks and background jobs are thin adapters over the
   same domain services. No capability exists only in the UI. The coverage matrix
   ([coverage-matrix.md](coverage-matrix.md)) is the contract.
2. **Modular monolith.** Domain modules — `tasks`, `projects`, `automation`, `scheduling`, `resources`,
   `reporting`, `identity`, `integrations` — own their models and services and talk to each other through
   service interfaces and domain events, never each other's tables.
3. **Events, not callbacks.** Domain services publish events; automations, webhooks, notifications, realtime
   fan-out and the audit log are consumers.
4. **Tenant on every row.** `TenantScoped` adds `tenant_id`; Postgres row-level security enforces it.
5. **Configuration by environment only**, secrets generated at install time.

## Runtime topology

| Container | Image | Command | Role |
| --- | --- | --- | --- |
| `web` | `glasshaus-web` | nginx | Static SPA, reverse proxy for `/api` and WebSockets, security headers |
| `api` | `glasshaus` | uvicorn | REST API (OpenAPI 3.1), WebSockets, metrics |
| `worker` | `glasshaus` | arq | Jobs, cron, automation execution, outbound webhooks |
| `mcp` | `glasshaus` | glasshaus-mcp | MCP server (Streamable HTTP; stdio for local use) |
| `migrate` | `glasshaus` | one-shot | Alembic migrations + idempotent seed before app start |
| `postgres` | `postgres:16-alpine` | — | Primary store |
| `redis` | `redis:7-alpine` | — | Cache, pub/sub, job queue |
| `backup` | `postgres:16-alpine` | backup loop | Scheduled `pg_dump` with retention |

## Request path

```
REST route / MCP tool / worker job          (thin adapters: parse, call, serialize)
        │  ServiceContext(session, actor)
        ▼
domain service  ── authz.require_project(...)  roles ∩ token scopes; invisible → 404
        │       ── events.emit(...)            outbox row in the same transaction
        ▼
PostgreSQL (RLS: tenant_id = app.tenant_id)  ──commit──▶  relay → Redis stream + pub/sub
```

- `ServiceContext` carries the `Actor` (tenant, user, org role, auth method, token scopes, client id).
- One transaction per request; `app.tenant_id` is set transaction-locally before any tenant data is read.
- The API, worker and MCP server connect as `glasshaus_app` (no `SUPERUSER`/`BYPASSRLS`); the API refuses to
  start in production if its role would bypass RLS. Only migrations and backups use the owner role.
- Domain events go to the `domain_events` outbox, are relayed after commit to the Redis stream
  `glasshaus:events` (consumers) and `glasshaus:events:<tenant>` pub/sub (realtime), and the worker sweeps any
  that were not relayed.

## Event consumers and realtime

- **Consumers** (`glasshaus/core/consumers.py`): handlers register with `@handles("comment.created", …)` and run in
  the worker through the Redis Streams consumer group `glasshaus-workers`. Delivery is at-least-once, so handlers
  are idempotent (notifications are unique per event and recipient). Failures are retried after 60 s and moved to
  `glasshaus:events:dead` after 5 deliveries. Automations, webhooks and the audit log plug in the same way.
  Each batch runs events for different aggregates in parallel (up to 8) and events for the same aggregate (a
  task and its comments) in stream order.
- **Realtime** (`WS /api/v1/ws`): each connection subscribes to its tenant's pub/sub channel and forwards only
  event identifiers for projects the user can read (visibility cached for 60 s, reset on membership changes).
  Browsers refetch through the normal API, so no data bypasses authorization; they collect stale query keys for
  400 ms and refetch each once. Cookie-authenticated sockets must come from the app's own origin.

## Scheduling

`glasshaus/scheduling/cpm.py` is pure, I/O-free maths shared by every scheduling feature:

- A task occupies `[start, due]` (inclusive calendar days); a task with one date is a one-day milestone.
- Dependency constraints (lag in days, negative = lead): FS `succ.start ≥ pred.due + 1 + lag`,
  SS `succ.start ≥ pred.start + lag`, FF `succ.due ≥ pred.due + lag`, SF `succ.due ≥ pred.start − 1 + lag`.
- **Critical path:** forward pass (planned starts act as "start no earlier than"), backward pass from the
  project finish; slack = late start − early start; slack ≤ 0 is critical.
- **Propagation:** successors only ever move later and keep their duration; cycles are rejected when a
  dependency is created.
- Rescheduling is opt-in per project (`auto_schedule`); otherwise violations surface as warnings and
  `POST /reschedule` previews (then applies) the fix.

## Automations

`glasshaus/automation/` turns *trigger → conditions → actions* rules into service-layer calls.

- **Triggers:** `task_created`, `task_updated` (optionally one field), `status_changed` (to a status or
  category), `comment_created` come from domain events in the consumer; `due_soon` (every 10 min) and
  `scheduled` (daily/weekly/monthly in an IANA zone, every minute) come from worker crons. Recurring tasks use
  the same scheduler.
- **Execution** (`runner.fire`): one transaction per run, as an `automation` principal scoped to the rule's
  project. A run is claimed with a unique `(rule_id, dedupe_key)` row (event id, schedule occurrence, or task
  and due date), so redelivery and concurrent workers never double-run. Conditions are evaluated against the
  task's current state; non-matching events leave no trace. If any action fails, all are rolled back and the
  run is logged as failed.
- **Webhooks** go out after commit: resolved once, every address checked (loopback, link-local and metadata
  always refused; private networks only with `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE`), connected by IP so DNS
  rebinding cannot redirect, no redirects, 10 s timeout, signed with
  `X-Glasshaus-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`. Retrying a run whose actions
  succeeded resends only the failed webhooks.
- **Loop prevention:** events caused by automations are ignored unless a rule opts in (`run_on_automation`);
  a rule never reacts to its own changes; more than 20 runs on one task in a minute trips a guard; rules ignore
  events older than themselves.
- **Safety:** task text is data. Placeholders (`{{task.key}}` …) are substituted from a fixed list, never
  evaluated, and nothing in task content can choose which actions run.
- **Templates** snapshot statuses, fields, shared views, tasks (dates as offsets), dependencies, rules and
  recurring tasks; instantiating remaps every id and shifts dates to a chosen start.

## Time, workload and reporting

- **Time entries** belong to a task and its project. You see your own, organization admins see all,
  and anyone who can read a project sees its entries. Logging needs task-edit rights, authors change
  their own entries and project admins can change any in their project. One running timer per person;
  stopping it logs the elapsed time (rounded up to a minute, at most 24 hours).
- **Workload** (`insights/calc.py`, pure): remaining work = estimate − logged, spread evenly over the
  working days between start and due (a single date is a one-day task), compared per day or week with
  each person's capacity (`capacity_minutes` per working day, `working_days`). Undated, overdue and
  unestimated work is reported separately rather than guessed into the plan.
- **Project reports** are computed on read from current task state: status mix, burn-up (scope and
  done per day), weekly throughput, lead time (created → completed), estimate vs actual. Burn-up uses
  current status and timestamps, not a full status history.
- **Health** (portfolios, dashboards): off track when ≥20 % of open work is overdue or the finish has
  slipped more than a week past the latest baseline; at risk with any overdue work or slip.
- **Dashboards** store only a widget layout; every widget reads the normal, permission-checked APIs.
- **OKRs and portfolios** are organization-wide (hidden from guests). Task-based key results and
  project health only show for projects the viewer can read.
- CSV exports neutralize spreadsheet formulas in text cells.

## Authorization model

| Level | Roles | Effect |
| --- | --- | --- |
| Organization | owner, admin, member, guest | owner/admin: everything in the tenant; guests see only projects they are added to |
| Workspace | admin, member, viewer | implies admin, editor, viewer on every project in the workspace |
| Project | admin, editor, commenter, viewer | explicit grant; the effective role is the highest of explicit and implied |
| Token scope | read, tasks:write, projects:write, admin | intersected with the user's permissions |

Permissions are defined once in `glasshaus/core/rbac.py`; REST and MCP enforce the same checks because they
call the same services.

## Governance, SSO and integrations

- **Audit:** a catch-all event consumer (`audit/handlers.py`) writes every domain event to `audit_log`
  (idempotent on the event id); sign-ins, SSO, provisioning and MCP calls are written directly. A nightly
  worker job applies each organization's retention (`org_settings`).
- **SSO** (`sso/`): identity providers per organization; flow state in Redis (10 minutes, single use);
  `user_identities` links IdP subjects to accounts. **SCIM** (`scim/`, mounted at `/scim/v2`) authenticates
  with hashed `ghs_` tokens and runs through the same services and events as the API.
- **Integrations** (`integrations/`): a catch-all consumer matches events to outbound integrations,
  commits `integration_deliveries` rows, then sends through the SSRF-checked webhook sender with no
  transaction open (a row's first retry is a five-minute lease away, so a crash mid-send is retried); a
  worker job claims due rows the same way and retries with backoff. GitHub/GitLab payloads are verified and turned into comments/status changes by the
  service layer acting as an `integration` principal. Email-to-task polls IMAP from the worker. Secrets
  are encrypted with Fernet (`core/crypto.py`).
- **Hardening** (`api/hardening.py`): security headers, a 10 MB body cap and a Redis per-principal rate
  limit on REST and SCIM; account-level login throttling in `identity/service.py`.

## MCP server and OAuth

- `mcp_server/server.py` builds the server; `tools_core.py`, `tools_plan.py` and `resources.py` are thin
  adapters. Each call goes through `runtime.invoke`: resolve the actor from the bearer token, check the
  tool's scope, Redis rate limit per user, run the service call in one unit of work (RBAC, RLS, events as
  for REST), then write an `audit_log` row (user, client, redacted arguments, outcome, duration).
- The MCP server is its own OAuth 2.1 authorization server (MCP SDK routes: `/authorize`, `/token`,
  `/register`, `/revoke`, RFC 8414/9728 metadata). `/authorize` stores the request and redirects to the
  web app's `/oauth/consent`; approving there (session-authenticated REST call) issues a single-use code
  bound to the PKCE challenge, user and tenant. Tokens are random strings stored as SHA-256 hashes in
  `oauth_grants`, grouped by consent (`family_id`): refresh tokens rotate, reuse revokes the family,
  and disconnecting an app revokes it. OAuth tables are global (clients register before sign-in);
  `audit_log` is tenant-scoped under RLS.
- OAuth requires an HTTPS issuer (or localhost); otherwise the server accepts personal API tokens only.
- Untrusted content: tool and resource descriptions mark user-written text as data; destructive tools
  return previews unless `confirm=true`; nothing calls tools on the server side.

## Backend layout

```
backend/src/glasshaus/
  config.py          settings (GLASSHAUS_* env vars)
  logs.py            structlog configuration
  observability.py   Prometheus metrics, OpenTelemetry
  db.py              async engine/session
  redis_client.py    shared Redis client
  core/              context, errors, rbac, authz, events (outbox), ORM base, shared schemas
  identity/          users, sessions, API tokens, workspaces (models, schemas, service, security)
  projects/          projects, members, workflow statuses
  tasks/             tasks: search, CRUD, bulk, soft delete
  fields/            custom field definitions and typed value validation
  collab/            comments, @mentions, notifications (+ event handlers), activity feed
  views/             saved views (filters, grouping, sorting, columns)
  scheduling/        dependencies, critical path (cpm.py), auto-rescheduling, baselines, slip warnings
  realtime.py        WebSocket fan-out filtering
  onboarding/        first-run tour, checklist and tip state per person (milestones derived from work)
  ai/                optional assistant: provider interface (Claude, OpenAI-compatible, fake) and features
  models/            aggregate import of every model (for Alembic)
  dbroles.py         least-privilege app role management
  api/               FastAPI routers (REST adapters), auth dependency, problem details
  mcp_server/        MCP adapters (tools, resources, prompts)
  worker.py          arq worker settings and jobs
  migrations/        Alembic environment and versions
  seed.py            baseline + demo data
  cli.py             `glasshaus migrate|downgrade|seed|wait`
```


## Observability

- Logs: JSON to stdout (structlog), request-scoped context.
- Metrics: `/metrics` on the API (`glasshaus_http_requests_total`, `glasshaus_http_request_duration_seconds`).
- Traces: OTLP/HTTP when `GLASSHAUS_OTEL_ENABLED=true`.
- Health: `/healthz` (liveness), `/readyz` (Postgres + Redis); worker liveness via `arq --check`.
