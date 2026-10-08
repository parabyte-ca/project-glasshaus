# Changelog

All notable changes to Project Glasshaus are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0 minor versions map to delivery phases.

## [Unreleased]

## [0.3.0] - 2026-10-08

Phase 2 — views, custom fields, comments, activity feed.

### Added
- Typed custom fields per project (text, number, date, single/multi select, person, checkbox, URL) with
  validation, required fields, filtering (`cf=`), sorting (`sort_field=`), and safe clean-up when options or
  fields are removed.
- Comments in markdown with @mentions (`@[Name](user:<id>)` or `@email`), editing by the author and moderation
  by project admins.
- In-app notifications for mentions, assignments and comments on your tasks, produced by idempotent event
  consumers (Redis Streams consumer group with retry and dead-lettering) that later phases reuse.
- Activity feed for tasks, projects or everything you can see, built from the domain-event log.
- Saved views (list, board, table; personal or shared) holding filters, grouping, sorting and columns; run a view
  through the API.
- Live updates over WebSocket (`/api/v1/ws`): identifiers only, filtered by project visibility, origin-checked.
- Web UI: list, board (drag and drop between and within columns) and virtualized table views; toolbar for search,
  priority, grouping, sorting and completed tasks; saved-view picker and save; task drawer with field editing,
  markdown description, comments with an @mention picker and activity; project settings for custom fields;
  notifications menu.
- Demo data includes custom fields, comments with mentions and shared views.
- Account page with a change-password form (signs you out everywhere, then back to sign-in).

### Changed
- Domain events record their project (`project_id`); existing events are backfilled.
- Response schemas in the OpenAPI document mark always-present fields as required, so generated clients are
  accurate.

## [0.2.1] - 2026-10-07

### Security
- Container images apply OS security updates at build time (`apk upgrade` / `apt-get upgrade`); the web image
  had 42 fixable HIGH findings from its nginx base (curl, expat, libuuid, pcre2, OpenSSL, c-ares, libxml2).
  `UPGRADE_OS_PACKAGES=false` exists only for networks that block the package mirrors.

### Changed
- CI scans both container images on every pull request with the same Trivy gate as the release workflow.

## [0.2.0] - 2026-10-07

Phase 1 — data model, authentication, RBAC, core task and project API.

### Added
- Domain model: organizations (tenants), users, workspaces and members, projects and members, configurable
  workflow statuses per project, tasks (subtasks, priority, assignee, dates, estimate, tags, ordering, soft
  delete, optimistic concurrency), API tokens, refresh sessions, domain-event outbox.
- Service layer (`ServiceContext` + per-module services) shared by every adapter.
- Authentication: email/password sign-in (argon2id), short-lived JWT access cookie, rotating refresh token,
  double-submit CSRF protection, login rate limiting, personal API tokens with scopes.
- Authorization: organization, workspace and project roles intersected with token scopes; invisible
  resources return 404.
- Tenant isolation with PostgreSQL row-level security (default deny) and a least-privilege `glasshaus_app`
  database role created by `migrate`; the API refuses to start in production as a role that bypasses RLS.
- REST API `/api/v1` (auth, users, tokens, workspaces, projects, members, statuses, tasks incl. search,
  filters, sorting, cursor pagination, bulk update, dry-run delete, restore, `If-Match`), RFC 9457 errors,
  stable operation IDs; OpenAPI 3.1 committed at `docs/openapi.json` with drift tests.
- Domain events relayed to a Redis stream and per-tenant pub/sub; worker sweep for unrelayed events.
- Web UI: sign-in, project navigation, create workspace/project, task list with quick add, status and
  priority changes; typed API client generated from OpenAPI.
- First owner account bootstrapped from `GLASSHAUS_ADMIN_EMAIL` / `GLASSHAUS_ADMIN_PASSWORD`; deterministic
  demo data generated through the service layer (`make demo`).
- Feature → REST → event → MCP coverage matrix.

### Changed
- `GLASSHAUS_SECRET_KEY` must be at least 32 characters in production.
- `setup.sh` and `update.sh` generate any missing secrets (new: `POSTGRES_APP_PASSWORD`, `GLASSHAUS_ADMIN_PASSWORD`).

## [0.1.0] - 2026-10-07

Phase 0 — scaffold.

### Added
- Monorepo layout: `backend/` (FastAPI, SQLAlchemy 2 async, Alembic, arq worker, MCP server) and
  `frontend/` (React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query).
- Docker Compose stack: `api`, `web`, `worker`, `mcp`, `postgres`, `redis`, one-shot `migrate`, scheduled `backup`.
  Non-root, read-only containers with healthchecks; host ports 8470 (web), 8471 (API), 8472 (MCP).
- Health (`/healthz`, `/readyz`), version (`/api/v1/version`), Prometheus metrics (`/metrics`),
  structured JSON logging, optional OpenTelemetry tracing.
- MCP server skeleton (official Python SDK 2.x, Streamable HTTP at `/mcp`, stdio for local use) with a
  `server_info` tool.
- Multi-tenant foundation: `tenants` table and `TenantScoped` mixin; idempotent seed and demo-data generator.
- `setup.sh` (idempotent installer), `update.sh` (backup, upgrade, health check, automatic rollback),
  backup/restore scripts, version bump and consistency checks.
- Makefile, pre-commit hooks (ruff, eslint, prettier, shellcheck, gitleaks), GitHub Actions for lint, test,
  smoke test, dependency/filesystem/image scanning and multi-arch image publishing on tags.
- Dark mode, skip link and version display in the web shell.

[Unreleased]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/parabyte-ca/project-glasshaus/releases/tag/v0.1.0
