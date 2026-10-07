#!/usr/bin/env bash
# Safe upgrade: backup -> fetch -> build/pull -> migrate -> restart -> health check -> rollback on failure.
#   ./update.sh [--pull] [--no-git] [--version X.Y.Z]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/scripts/lib.sh"
cd "$ROOT_DIR"

PULL=0 GIT=1 TARGET=""
while (( $# )); do
  case "$1" in
    --pull) PULL=1 ;;
    --no-git) GIT=0 ;;
    --version) TARGET="${2:?--version needs a value}"; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

[[ -f "$ENV_FILE" ]] || die ".env not found; run ./setup.sh first"
PREV_VERSION="$(get_env GLASSHAUS_VERSION)"
PREV_SHA="$(get_env GLASSHAUS_BUILD_SHA)"

info "Backing up database"
compose up -d postgres >/dev/null
wait_healthy 60 postgres || die "postgres is not healthy; aborting before any change"
BACKUP="$(backup_now "pre-update-${PREV_VERSION}")" || die "backup failed; aborting before any change"
ok "backup: $BACKUP"

if [[ "$GIT" == 1 && -d .git ]]; then
  info "Fetching source"
  if ! git diff --quiet || ! git diff --cached --quiet; then
    die "uncommitted changes in the checkout; commit/stash or use --no-git"
  fi
  git pull --ff-only
fi
NEW_VERSION="${TARGET:-$(tr -d '[:space:]' < VERSION)}"
info "Upgrading ${PREV_VERSION} -> ${NEW_VERSION}"

rollback() {
  warn "update failed; rolling back to ${PREV_VERSION}"
  set_env GLASSHAUS_VERSION "$PREV_VERSION"
  set_env GLASSHAUS_BUILD_SHA "$PREV_SHA"
  restore_dump "$BACKUP" && ok "database restored from $BACKUP"
  compose up -d --remove-orphans
  if wait_healthy 180 api worker mcp web; then
    warn "rolled back to ${PREV_VERSION}. Source checkout is still at the new revision; see logs above."
  else
    die "rollback did not become healthy; restore manually with scripts/restore.sh $BACKUP"
  fi
  exit 1
}

set_env GLASSHAUS_VERSION "$NEW_VERSION"
set_env GLASSHAUS_BUILD_SHA "$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
if [[ "$PULL" == 1 ]]; then compose pull api web || rollback
else compose build || rollback; fi

info "Applying migrations and restarting"
compose up -d --remove-orphans || rollback
wait_healthy 180 api worker mcp web || { compose logs --tail 50 migrate api; rollback; }
ok "Project Glasshaus ${NEW_VERSION} is healthy (pre-update backup: $BACKUP)"
