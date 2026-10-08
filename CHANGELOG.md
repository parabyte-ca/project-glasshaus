# Changelog

All notable changes to Project Glasshaus are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0 minor versions map to delivery phases.

## [Unreleased]

### Added
- **Azure OpenAI** for the AI assistant through the `openai` provider: `GLASSHAUS_AI_AUTH_HEADER=api-key`,
  optional `GLASSHAUS_AI_API_VERSION` for classic deployment URLs, and an automatic retry with
  `max_completion_tokens` for models that refuse `max_tokens`. See `docs/ai.md`.

### Fixed
- The web container now re-resolves the API's address, so `/api` keeps working when the `api` container
  is recreated on its own (for example `docker compose up -d` after an `.env` change).

## [0.9.0] - 2026-10-08

Phase 8 — optional in-app AI, polish, accessibility and end-to-end tests.

### Added
- **AI assistant (optional, off by default):** written status updates, task drafting (proposals you add
  one by one), risk flags with evidence, and plain-language task search. Provider-agnostic: Claude via the
  Anthropic SDK (`claude-opus-5-5` by default, structured outputs, server-side refusal fallbacks), any
  OpenAI-compatible server such as Ollama or LM Studio, or a fake provider for demos and tests. Needs a
  server provider and an admin switch with per-feature settings; rate limited per person and audited
  without content. REST `/api/v1/ai/*`, MCP tools `ai_status`, `ai_status_report`, `ai_draft_tasks`,
  `ai_flag_risks`, `ai_search_tasks`. See `docs/ai.md`.
- **Command palette** (Ctrl K / ⌘ K): pages, projects, task search by key or title, and *Ask* with the
  assistant.
- **Keyboard shortcuts** (`?` for help, `/`, `c`, `g` sequences) and an accessible dialog component.
- **Installable app:** service worker with an offline app shell (static files only) and a richer
  manifest.
- **End-to-end tests** with Playwright (`e2e/`, `make test-e2e`, CI job): project and task flows, all
  layouts, the palette, the assistant, PWA, and axe WCAG 2.1 AA scans of every screen in light and dark
  themes and on a phone viewport. `docs/accessibility.md` covers the manual checks.

### Fixed
- Dark-mode contrast of secondary text, out-of-month calendar days, the page background under wide
  content, sideways scrolling on narrow screens, and keyboard access to scrolling regions (board, table,
  timeline, wide tables).

## [0.8.0] - 2026-10-08

Phase 7 — governance, single sign-on, provisioning, integrations, hardening and performance.

### Added
- **Admin console** for owners and admins: people (add, role, deactivate/reactivate, password reset,
  sign out everywhere), single sign-on, provisioning, integrations, audit log, data & retention.
- **Single sign-on** with OpenID Connect (PKCE, nonce, signed ID tokens) and SAML 2.0 (signed responses or
  assertions, replay protection), just-in-time accounts, allowed domains and optional SSO enforcement
  (owners keep password sign-in). Sign-in page shows the organization's providers.
- **SCIM 2.0** provisioning at `/scim/v2` (Users, Groups as workspaces, filtering, PATCH) with revocable
  tokens.
- **Integrations:** Slack, Microsoft Teams and HMAC-signed webhooks with event selection, project scope,
  retries with backoff and a delivery log; GitHub and GitLab linking (`fixes KEY-12` completes on merge);
  email-to-task over IMAP; personal iCalendar feeds for Google, Outlook/Microsoft 365 and Apple calendars.
- **Full audit log** of every domain change, sign-in (success and failure), SSO, provisioning, export and
  MCP call, with filters and paging; **retention** settings with a nightly purge; **organization export**
  (zip of JSON Lines, secrets excluded).
- MCP tools `manage_users`, `get_org_settings`, `update_org_settings` and `manage_integrations`
  (destructive actions preview first).
- `scripts/bench.py` latency benchmark; docs for SSO/SCIM, integrations and the ASVS L2 baseline.

### Changed
- Third-party secrets are encrypted at rest with a key derived from `GLASSHAUS_SECRET_KEY`.
- The event consumer handles new events before retrying failed ones, so a retry backlog never delays
  live work.

### Security
- Security headers (`nosniff`, `DENY`, strict API CSP, `no-store`, HSTS on HTTPS), a 10 MB request cap and
  a per-principal REST/SCIM rate limit (`GLASSHAUS_API_RATE_LIMIT_PER_MINUTE`).
- Login throttling per account regardless of client address; common, repetitive and name-based passwords
  are refused.
- Deactivating a person ends their sessions immediately.

## [0.7.0] - 2026-10-08

Phase 6 — MCP server, OAuth 2.1 and AI assistant integrations.

### Added
- MCP server with 53 tools covering projects, tasks, bulk changes, statuses, custom fields, comments,
  views, dependencies and schedules, baselines, automations (including run-now and retries), recurring
  tasks, templates, time and timers, timesheets, workload, reports, status-summary data, dashboards,
  portfolios, OKRs and the audit log. Destructive tools return a dry-run preview unless `confirm=true`.
- MCP resources for projects, project reports and status, tasks, saved views and dashboards, and prompt
  templates for a weekly status, risk review, sprint planning and a stand-up digest.
- OAuth 2.1 for MCP clients: dynamic client registration, PKCE, RFC 8414/9728 discovery, a consent page
  in the web app, rotating refresh tokens with reuse detection, revocation, and **Account → Connected
  apps**. Personal API tokens also work, and can now be created under **Account → API tokens**.
- Per-tool scope checks mirroring RBAC, a per-user rate limit and an audit log of every MCP call
  (`GET /api/v1/audit-log`).
- `GET /api/v1/projects/{id}/status-summary` and `POST /api/v1/automation-rules/{id}/run`.
- Tested configuration examples for GitHub Copilot (VS Code), Copilot Studio, Microsoft 365 Copilot
  (declarative agent with MCP plugin, plus an OpenAPI 3.0 API plugin fallback), Claude Desktop, Claude
  Code and generic clients; an MCP conformance suite; and `examples/agent.py`.

### Fixed
- Read-only API tokens could create or change portfolios, objectives, key results, check-ins and
  dashboards; those writes now require the matching token scope.

## [0.6.0] - 2026-10-08

Phase 5 — time tracking, workload, reporting, dashboards, portfolios and OKRs.

### Added
- Time tracking: log time on tasks (billable flag, notes), a one-click timer shown in the header,
  per-person weekly timesheets (admins can view anyone's), a person × project time report and CSV
  export.
- Capacity per person (hours per working day, working weekdays) and a workload view comparing planned
  remaining work (estimate − logged, spread over task dates) with capacity per week or day,
  highlighting overload, undated, overdue and unestimated work.
- Project reports: burn-up, weekly throughput, status mix, lead time (median and 85th percentile),
  estimate vs actual, open work by assignee, health rating, and CSV export of tasks.
- Dashboards with widgets (my tasks, my time, team time by project, workload, project status, burn-up,
  throughput, portfolio, objective); private or shared.
- Portfolios rolling up project progress, overdue work, baseline slip and health.
- OKRs: objectives per period with weighted key results measured by a number or by task completion in a
  project (optionally one tag), check-ins with confidence, and alignment to parent objectives.
- Charts are accessible (keyboard readout, data tables, colour-blind-safe palette in light and dark).
- Demo data includes logged time, a portfolio, an objective and a shared dashboard.

## [0.5.0] - 2026-10-08

Phase 4 — automation engine and templates.

### Added
- Automation rules per project: trigger (task created/updated, status changed, comment added, due soon,
  daily/weekly/monthly schedule in any time zone) → conditions (priority, status, assignee, tags, title, days
  until due, subtask, custom fields) → actions (set status/priority/due date/custom field, assign/unassign,
  add/remove tags, create subtask, post comment, notify people, call a webhook). Text supports placeholders
  such as `{{task.key}}`.
- Exactly-once runs per event or occurrence, atomic actions, a run log with errors and one-click retry (only
  failed webhooks are resent when the actions succeeded), dry run against any task, and loop prevention.
- Signed outbound webhooks (`X-Glasshaus-Signature`, HMAC-SHA256) with SSRF protection; private networks are
  opt-in via `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE` for homelab targets.
- Recurring tasks on daily, weekly or monthly schedules.
- Project templates: save a project's statuses, fields, shared views, tasks (relative dates), dependencies,
  rules and recurring tasks; start new projects from them.
- Web UI: project settings tabs for automations (rule builder, dry run, run log, retry), recurring tasks and
  templates; "Start from" template choice when creating a project; automation-made comments and changes are
  labelled "Automation".
- Demo data includes rules, a recurring review and a "Website launch" template.

### Changed
- `make dev-deps` uses its own Compose project (`glasshaus-dev`), so it never touches a stack running from
  another directory on the same host, and Makefile targets read `.env` correctly.

## [0.4.0] - 2026-10-08

Phase 3 — dependencies, timeline/Gantt, critical path, calendar.

### Added
- Task dependencies: finish-to-start, start-to-start, finish-to-finish and start-to-finish, with lag or lead in
  days; cycles and duplicates are rejected.
- Critical path calculation (early/late dates, slack, critical tasks, project finish).
- Auto-rescheduling (opt-in per project): changing dates or adding dependencies pushes dependent tasks later,
  keeping their durations; otherwise a preview-then-apply reschedule fixes violations on demand.
- Baselines: snapshot planned dates and compare per task and for the project finish.
- Slip warnings: overdue tasks, violated dependencies, tasks and the project finish behind the latest baseline.
- Calendar-window task filter (`scheduled_from` / `scheduled_to`).
- Web UI: timeline (Gantt) with dependency arrows, critical-path highlighting, baseline ghost bars, today line,
  day/week zoom, drag to move or resize and arrow keys for keyboard users; month calendar; start date and a
  dependency editor in the task drawer; auto-schedule toggle, baseline save, dependency check and warnings.
- Demo data includes a dependency chain and an "Initial plan" baseline per project.

### Changed
- Migration template generates modern typing syntax.
- The web app loads layouts, the task drawer, settings and account pages on demand (initial bundle 298 kB,
  down from 504 kB); busy calendar days expand with "+N more".

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

[Unreleased]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/parabyte-ca/project-glasshaus/releases/tag/v0.1.0
