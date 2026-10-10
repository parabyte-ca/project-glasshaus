---
name: release
description: Cut a Glasshaus release (version bump, changelog, generated files, checks, local stack and e2e, PR). Use when finishing a feature batch or when asked to "release", "bump the version" or "ship 0.x".
---

# Releasing Glasshaus

One release per PR. Minor version for features, patch for fixes.

## Steps

1. **Version and generated files**
   ```bash
   scripts/bump-version.sh X.Y.Z   # VERSION, pyproject, package.json, uv.lock, OpenAPI, .env.example, README status
   make openapi                    # docs/openapi.json, frontend/src/api/schema.d.ts, Copilot spec
   ```
2. **CHANGELOG.md**: add `## [X.Y.Z] - YYYY-MM-DD` under `[Unreleased]` (Keep a Changelog headings,
   plain language, what people can now do). Then `scripts/release_docs.py` rebuilds the compare links.
3. **Docs that usually need a touch**
   - `README.md`: the roadmap row for this phase, feature bullets, MCP tool count (the server's
     `list_tools()` length).
   - `docs/coverage-matrix.md`: every new MCP tool (a test fails otherwise).
   - Feature guides in `docs/` (`reports.md`, `ai.md`, …) and `.env.example` for new settings.
4. **Checks**: `make check` (ruff, mypy on src *and* tests, eslint, prettier, pytest, vitest,
   `scripts/check-version.sh`). Run `mypy src tests`, not only `src`; CI does.
5. **Local stack and e2e** (when the UI or API changed): build and start the Compose stack, then
   ```bash
   cd e2e && E2E_ADMIN_PASSWORD=… npx playwright test
   ```
   Prefer upgrading the existing local stack with `./update.sh --no-git` over a bare `compose up`:
   it exercises the pre-flight check and the migrations on real data, like a user's upgrade.
   The AI spec needs `GLASSHAUS_AI_PROVIDER=fake`. Use `{ exact: true }` for labels that are
   substrings of region names ("Question" vs "Ask a question").
6. **Commit, push, draft PR**; after merge the owner tags and pushes **that one tag** (pushing more than
   three tags at once starts no workflows, so nothing would be published):
   `git fetch origin main && git tag vX.Y.Z origin/main && git push origin vX.Y.Z`
   (or `scripts/release-tags.sh --tag --push`), then runs `update.sh` on the server.
   `scripts/release-tags.sh` lists every release and its tag; CI (Repo hygiene, and a daily
   *Release tags* run) fails when a release merged over a day ago has no tag. Only the newest version's
   tag publishes images and a GitHub Release; older tags just mark history.

## Conventions

- Canadian English, short sentences, no jargon in UI text and changelog.
- New AI features are opt-in (`ai_features`), send the least data, wrap untrusted text in the
  data block, and are audited as `ai.<feature>`.
- New tenant tables: add to `RLS_TABLES` in `core/orm.py` and call `enable_rls()` in the migration.
- Network calls (AI, email, webhooks) happen outside database transactions.
- Scheduled per-person features (report emails, alerts) run as that person, move `next_run_at`
  before doing the work, and drop themselves when the person or their access is gone.
- Ops scripts: `shellcheck` them; the backup container is POSIX `sh` (Alpine), the host scripts bash.
- Three images ship: `glasshaus` (backend), `glasshaus-web`, `glasshaus-backup` (postgres + `age` built
  from the pinned `AGE_VERSION` with `golang:1.27-alpine`, so Trivy sees a patched Go stdlib; the
  upstream release binaries lag on Go fixes). New images go in the CI scan and release matrices and
  in `update.sh --pull`. The image ends with a non-root `USER` (Trivy DS-0002).
- The audit log is append-only and hash-chained by a database trigger: never write to `audit_log`
  except by insert; tests that need old entries backdate them with `tests.factories.owner_session()`.
- Performance: list endpoints must not query per row. Batch permission checks with
  `core.authz.prime_project_roles`, aggregate with `GROUP BY` / `count().filter(...)`, never send
  unbounded `IN` lists, and add a query-count case to `tests/test_performance.py` for new list pages.
  Live updates: `task.updated` is patched into open lists by `lib/realtime.ts`; new list query keys
  under `['tasks', projectId, …]` must be a view config object or they are simply refetched.
- Personal data: new tables referencing users are picked up by the personal export automatically;
  add them to `people.privacy.erase_person` when they hold credentials, devices or personal text.

## Cloud sandbox notes

- No `rsync`: copy the tree with `git ls-files -co --exclude-standard -z | tar --null -T - -cf - | tar -xf - -C <dest>`.
- Docker builds go through the agent proxy; its port changes per session (`echo $HTTPS_PROXY`), so
  update the build args in the stack's `docker-compose.override.yml` (it needs `backup: { build: *build }`
  too). The proxy blocks Alpine's package mirror (proxy.golang.org works), and local Trivy cannot fetch
  its database, so image scans are confirmed in CI.
- Tag pushes are blocked from the sandbox; the owner pushes tags.
- Changing UI text (toasts, links, headings) breaks e2e selectors that use it: grep `e2e/tests` for the
  old text. Scope link lookups to a landmark (`getByRole('navigation', { name: 'Main' })`) when the same
  link can appear twice on a page.
- After editing backend messages, run `uv run ruff format` (long strings get re-wrapped).
- Page titles are set in an effect; with the data router, assert them with `waitFor`.
