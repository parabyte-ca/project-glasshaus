# Changelog

All notable changes to Project Glasshaus are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0 minor versions map to delivery phases.

## [Unreleased]

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

[Unreleased]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/parabyte-ca/project-glasshaus/releases/tag/v0.1.0
