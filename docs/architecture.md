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
- **Realtime** (`WS /api/v1/ws`): each connection subscribes to its tenant's pub/sub channel and forwards only
  event identifiers for projects the user can read (visibility cached for 60 s, reset on membership changes).
  Browsers refetch through the normal API, so no data bypasses authorization. Cookie-authenticated sockets must
  come from the app's own origin.

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

## Authorization model

| Level | Roles | Effect |
| --- | --- | --- |
| Organization | owner, admin, member, guest | owner/admin: everything in the tenant; guests see only projects they are added to |
| Workspace | admin, member, viewer | implies admin, editor, viewer on every project in the workspace |
| Project | admin, editor, commenter, viewer | explicit grant; the effective role is the highest of explicit and implied |
| Token scope | read, tasks:write, projects:write, admin | intersected with the user's permissions |

Permissions are defined once in `glasshaus/core/rbac.py`; REST and MCP enforce the same checks because they
call the same services.

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
