#!/usr/bin/env bash
# CI/pre-commit guard: VERSION, backend/pyproject.toml and frontend/package.json must agree.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
v="$(tr -d '[:space:]' < "$root/VERSION")"
py="$(sed -nE 's/^version = "(.*)"/\1/p' "$root/backend/pyproject.toml" | head -1)"
js="$(sed -nE 's/^  "version": "(.*)",/\1/p' "$root/frontend/package.json" | head -1)"
[[ "$v" == "$py" && "$v" == "$js" ]] || { echo "version mismatch: VERSION=$v pyproject=$py package.json=$js" >&2; exit 1; }
grep -q "^## \[$v\]" "$root/CHANGELOG.md" || { echo "CHANGELOG.md has no entry for $v" >&2; exit 1; }
echo "version $v consistent"
