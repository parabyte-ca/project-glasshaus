#!/usr/bin/env bash
# Safe upgrade: fetch -> backup -> build/pull -> pre-flight on a copy -> migrate -> restart -> health
# check -> rollback on failure.
#   ./update.sh [--pull] [--no-git] [--version X.Y.Z] [--rollback-rev REV] [--skip-preflight]
# --rollback-rev: git revision whose docker-compose.yml to roll back with (default: HEAD before pulling).
# Pre-flight: the new release migrates a copy of the database and its API must become ready, all
# before the running release is touched; if it fails, nothing changes.
set -euo pipefail

main() {
  # shellcheck source=scripts/lib.sh
  source "$(dirname "$0")/scripts/lib.sh"
  cd "$ROOT_DIR"

  local args=("$@") pull=0 use_git=1 target="" rollback_rev="" preflight=1
  while (( $# )); do
    case "$1" in
      --pull) pull=1 ;;
      --no-git) use_git=0 ;;
      --version) target="${2:?--version needs a value}"; shift ;;
      --rollback-rev) rollback_rev="${2:?--rollback-rev needs a value}"; shift ;;
      --skip-preflight) preflight=0 ;;
      -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
      *) die "unknown option: $1" ;;
    esac
    shift
  done
  [[ -f "$ENV_FILE" ]] || die ".env not found; run ./setup.sh first"

  # 1. Remember the running release's compose file: a rollback must use the previous definition.
  if [[ -z "${GLASSHAUS_ROLLBACK_COMPOSE:-}" ]]; then
    GLASSHAUS_ROLLBACK_COMPOSE="$(mktemp -t glasshaus-rollback.XXXXXX.yml)"
    if [[ -n "$rollback_rev" ]]; then
      git show "${rollback_rev}:docker-compose.yml" > "$GLASSHAUS_ROLLBACK_COMPOSE" \
        || die "cannot read docker-compose.yml at $rollback_rev"
    else
      cp docker-compose.yml "$GLASSHAUS_ROLLBACK_COMPOSE"
    fi
    export GLASSHAUS_ROLLBACK_COMPOSE
  fi

  # 2. Fetch source. If this script changed, hand over to the new version before doing anything else.
  if [[ "$use_git" == 1 && -d .git ]]; then
    info "Fetching source"
    if ! git diff --quiet || ! git diff --cached --quiet; then
      die "uncommitted changes in the checkout; commit/stash or use --no-git"
    fi
    local before
    before="$(git rev-parse HEAD)"
    git pull --ff-only
    if ! git diff --quiet "$before" HEAD -- update.sh scripts/lib.sh; then
      info "update.sh changed; continuing with the new version"
      exec "$ROOT_DIR/update.sh" "${args[@]}" --no-git
    fi
  fi

  ensure_secrets  # new releases may require new secrets (e.g. POSTGRES_APP_PASSWORD in 0.2.0)
  local prev_version prev_sha new_version backup
  prev_version="$(get_env GLASSHAUS_VERSION)"
  prev_sha="$(get_env GLASSHAUS_BUILD_SHA)"
  new_version="${target:-$(tr -d '[:space:]' < VERSION)}"

  # 3. Back up before touching anything that matters.
  info "Backing up database"
  compose up -d postgres >/dev/null
  wait_healthy 60 postgres || die "postgres is not healthy; aborting before any change"
  backup="$(backup_now "pre-update-${prev_version}")" || die "backup failed; aborting before any change"
  ok "backup: $backup"

  rollback() {
    warn "update failed; rolling back to ${prev_version}"
    set_env GLASSHAUS_VERSION "$prev_version"
    set_env GLASSHAUS_BUILD_SHA "$prev_sha"
    export GLASSHAUS_COMPOSE_FILE="$GLASSHAUS_ROLLBACK_COMPOSE"
    restore_dump "$backup" && ok "database restored from $backup"
    compose up -d --remove-orphans
    if wait_healthy 180 api worker mcp web; then
      warn "rolled back to ${prev_version}. The source checkout is at the new revision; see the logs above."
    else
      die "rollback did not become healthy; restore manually with scripts/restore.sh $backup"
    fi
    exit 1
  }

  # 4. Build or pull, migrate (the migrate service runs first), restart, verify.
  info "Upgrading ${prev_version} -> ${new_version}"
  set_env GLASSHAUS_VERSION "$new_version"
  set_env GLASSHAUS_BUILD_SHA "$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
  if [[ "$pull" == 1 ]]; then compose pull api web backup || rollback
  else compose build || rollback; fi
  ensure_backup_key  # 0.22: backups are encrypted from now on

  if [[ "$preflight" == 1 ]]; then
    if ! preflight_check "$backup"; then
      set_env GLASSHAUS_VERSION "$prev_version"
      set_env GLASSHAUS_BUILD_SHA "$prev_sha"
      die "pre-flight failed: ${new_version} did not start on a copy of your data. Nothing was changed; ${prev_version} is still running. See the output above."
    fi
    ok "pre-flight: ${new_version} migrated a copy of the database and started cleanly"
  fi

  info "Applying migrations and restarting"
  compose up -d --remove-orphans || { compose logs --tail 50 migrate; rollback; }
  wait_healthy 180 api worker mcp web || { compose logs --tail 50 migrate api; rollback; }
  rm -f "$GLASSHAUS_ROLLBACK_COMPOSE"
  ok "Project Glasshaus ${new_version} is healthy (pre-update backup: $backup)"
}

main "$@"
exit
