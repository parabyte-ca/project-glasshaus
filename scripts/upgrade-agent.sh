#!/usr/bin/env bash
# Host helper for upgrades started in Admin > Updates. The app (in containers) can't run update.sh, so
# it leaves a request in the upgrade folder; this script, run every minute as root, picks it up, runs
# update.sh (backup, pre-flight on a copy, migrate, health check, rollback on failure) and writes its
# progress and log back for the Admin page.
#
#   scripts/upgrade-agent.sh            check for a request (what cron runs)
#   scripts/upgrade-agent.sh --install  run it every minute from /etc/cron.d (or print how to on TrueNAS)
#
# Extra update.sh options for app-started upgrades: GLASSHAUS_UPGRADE_ARGS in .env (only --pull and
# --skip-preflight are accepted).
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$ROOT_DIR"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

install_cron() {
  local self line
  self="$(readlink -f "$0")"
  line="* * * * * root $self >/dev/null 2>&1"
  ensure_upgrade_dir
  if [[ -d /etc/cron.d && -w /etc/cron.d ]] && [[ ! -f /etc/truenas_conf ]] && ! command -v midclt >/dev/null; then
    printf '# Glasshaus upgrade helper (see %s)\n%s\n' "$self" "$line" > /etc/cron.d/glasshaus-upgrade
    chmod 0644 /etc/cron.d/glasshaus-upgrade
    ok "installed /etc/cron.d/glasshaus-upgrade; Admin > Updates shows the helper within a minute"
  else
    info "Add a cron job that runs every minute as root (on TrueNAS: System > Advanced Settings > Cron Jobs):"
    printf '    Command:  %s\n    Run as:   root\n    Schedule: every minute (* * * * *)\n' "$self"
  fi
  "$self"  # check in now
}

field() {  # field NAME FILE -> a string value from a flat JSON file, without needing jq
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$2" | head -1
}

write_json() {  # write_json FILE key value ... (values are already safe: validated or ours)
  local file="$1" tmp out="{" sep=""
  shift
  while (( $# )); do
    out+="$sep\"$1\": \"$2\""
    sep=", "
    shift 2
  done
  tmp="$(mktemp "$file.XXXXXX")"
  printf '%s}\n' "$out" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$file"
}

main() {
  if [[ "${1:-}" == "--install" ]]; then install_cron; return; fi
  [[ "$(id -u)" == 0 ]] || die "run as root (update.sh needs Docker)"
  [[ -f "$ENV_FILE" ]] || die ".env not found; run ./setup.sh first"
  local dir
  dir="$(upgrade_dir)"
  ensure_upgrade_dir
  exec 9>"$dir/.lock"
  flock -n 9 || exit 0  # an upgrade is already running
  write_json "$dir/agent.json" last_seen "$(now)" helper "1"

  [[ -f "$dir/request.json" ]] || return 0
  local id version by
  id="$(field id "$dir/request.json")"
  version="$(field version "$dir/request.json")"
  by="$(field requested_by "$dir/request.json")"
  rm -f "$dir/request.json"
  [[ "$id" =~ ^[0-9a-f-]{36}$ && "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    warn "ignoring a malformed upgrade request"
    return 0
  }
  [[ "$by" =~ ^[A-Za-z0-9._%+@-]{0,320}$ ]] || by=""

  local args=() arg from started
  for arg in $(get_env GLASSHAUS_UPGRADE_ARGS); do
    case "$arg" in --pull|--skip-preflight) args+=("$arg") ;; *) warn "ignoring GLASSHAUS_UPGRADE_ARGS option $arg" ;; esac
  done
  from="$(get_env GLASSHAUS_VERSION)"
  started="$(now)"
  write_json "$dir/status.json" id "$id" state running from_version "$from" to_version "$version" \
    requested_by "$by" started_at "$started"
  : > "$dir/upgrade.log"
  chmod 0644 "$dir/upgrade.log"
  if "$ROOT_DIR/update.sh" "${args[@]}" >> "$dir/upgrade.log" 2>&1; then
    write_json "$dir/status.json" id "$id" state succeeded from_version "$from" \
      to_version "$(get_env GLASSHAUS_VERSION)" requested_by "$by" started_at "$started" finished_at "$(now)" \
      message "Upgraded to $(get_env GLASSHAUS_VERSION)."
  else
    write_json "$dir/status.json" id "$id" state failed from_version "$from" to_version "$version" \
      requested_by "$by" started_at "$started" finished_at "$(now)" \
      message "The upgrade stopped; $(get_env GLASSHAUS_VERSION) is running. See the log."
  fi
  write_json "$dir/agent.json" last_seen "$(now)" helper "1"
}

main "$@"
