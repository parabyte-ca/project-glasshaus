#!/usr/bin/env bash
# Set the release version everywhere it is recorded: scripts/bump-version.sh X.Y.Z
set -euo pipefail
new="${1:?usage: scripts/bump-version.sh X.Y.Z}"
[[ "$new" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "not a semantic version: $new" >&2; exit 1; }
root="$(cd "$(dirname "$0")/.." && pwd)"
echo "$new" > "$root/VERSION"
sed -i.bak -E "s/^version = \".*\"/version = \"$new\"/" "$root/backend/pyproject.toml" && rm "$root/backend/pyproject.toml.bak"
(cd "$root/frontend" && npm version "$new" --no-git-tag-version --allow-same-version >/dev/null)
(cd "$root/backend" && uv lock -q)
sed -i.bak -E "s/^GLASSHAUS_VERSION=.*/GLASSHAUS_VERSION=$new/" "$root/.env.example" && rm "$root/.env.example.bak"
echo "version set to $new — add a CHANGELOG.md entry, commit, then: git tag v$new"
