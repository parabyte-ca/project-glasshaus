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

## Backend layout

```
backend/src/glasshaus/
  config.py          settings (GLASSHAUS_* env vars)
  logs.py            structlog configuration
  observability.py   Prometheus metrics, OpenTelemetry
  db.py              async engine/session
  redis_client.py    shared Redis client
  models/            SQLAlchemy models (Base, TenantScoped, ...)
  api/               FastAPI routers (REST adapters)
  mcp_server/        MCP adapters (tools, resources, prompts)
  worker.py          arq worker settings and jobs
  migrations/        Alembic environment and versions
  seed.py            baseline + demo data
  cli.py             `glasshaus migrate|downgrade|seed|wait`
```

Domain modules (`glasshaus/<module>/{models,service,schemas,events}.py`) are introduced from Phase 1.

## Observability

- Logs: JSON to stdout (structlog), request-scoped context.
- Metrics: `/metrics` on the API (`glasshaus_http_requests_total`, `glasshaus_http_request_duration_seconds`).
- Traces: OTLP/HTTP when `GLASSHAUS_OTEL_ENABLED=true`.
- Health: `/healthz` (liveness), `/readyz` (Postgres + Redis); worker liveness via `arq --check`.
