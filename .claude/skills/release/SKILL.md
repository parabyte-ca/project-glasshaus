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
   The AI spec needs `GLASSHAUS_AI_PROVIDER=fake`. Use `{ exact: true }` for labels that are
   substrings of region names ("Question" vs "Ask a question").
6. **Commit, push, draft PR**; after merge the owner tags: `git tag vX.Y.Z && git push origin --tags`,
   then runs `update.sh` on the server.

## Conventions

- Canadian English, short sentences, no jargon in UI text and changelog.
- New AI features are opt-in (`ai_features`), send the least data, wrap untrusted text in the
  data block, and are audited as `ai.<feature>`.
- New tenant tables: add to `RLS_TABLES` in `core/orm.py` and call `enable_rls()` in the migration.
- Network calls (AI, email, webhooks) happen outside database transactions.

## Cloud sandbox notes

- No `rsync`: copy the tree with `git ls-files -co --exclude-standard -z | tar --null -T - -cf - | tar -xf - -C <dest>`.
- Docker builds go through the agent proxy; its port changes per session (`echo $HTTPS_PROXY`), so
  update the build args in the stack's `docker-compose.override.yml`.
- Tag pushes are blocked from the sandbox; the owner pushes tags.
