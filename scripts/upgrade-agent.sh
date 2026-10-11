#!/usr/bin/env bash
# Host helper for upgrades started in Admin > Updates. The app (in containers) can't run update.sh, so
# it leaves a request in the upgrade folder; this script, run every few minutes as root, picks it up, runs
# update.sh (backup, pre-flight on a copy, migrate, health check, rollback on failure) and writes its
# progress and log back for the Admin page.
#
#   scripts/upgrade-agent.sh              check for a request (what the schedule runs)
#   scripts/upgrade-agent.sh --install    run it every 15 minutes: /etc/cron.d if cron is installed, else a
#                                         systemd timer, else print what to schedule
#   scripts/upgrade-agent.sh --print      only print what to schedule (hosts whose scheduler is managed
#                                         elsewhere, e.g. a NAS web interface)
#   scripts/upgrade-agent.sh --uninstall  remove the cron job or systemd timer
#   --every N                             minutes between runs (1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30; default
#                                         15). An upgrade you start in the app begins within that time.
#
# Extra update.sh options for app-started upgrades: GLASSHAUS_UPGRADE_ARGS in .env (only --pull and
# --skip-preflight are accepted).
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"
cd "$ROOT_DIR"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

CRON_FILE=/etc/cron.d/glasshaus-upgrade
UNIT_DIR=/etc/systemd/system
UNIT=glasshaus-upgrade
EVERY=""  # minutes between runs; --install defaults to 15, a bare run (older cron lines) to 1

cron_spec() { if (( EVERY == 1 )); then printf '*'; else printf '*/%s' "$EVERY"; fi; }

print_schedule() {
  info "Schedule this command to run every $EVERY minute(s) as root:"
  printf '    %s --every %s\n' "$1" "$EVERY"
  printf '  cron line:  %s * * * * root %s --every %s >/dev/null 2>&1\n' "$(cron_spec)" "$1" "$EVERY"
}

install_schedule() {
  local self mode="$1"
  EVERY="${EVERY:-15}"
  self="$(readlink -f "$0")"
  ensure_upgrade_dir
  if [[ "$mode" == print ]]; then
    print_schedule "$self"
  elif [[ -d /etc/cron.d && -w /etc/cron.d ]] && { command -v cron || command -v crond; } >/dev/null 2>&1; then
    printf '# Glasshaus upgrade helper (see %s)\n%s * * * * root %s --every %s >/dev/null 2>&1\n' \
      "$self" "$(cron_spec)" "$self" "$EVERY" > "$CRON_FILE"
    chmod 0644 "$CRON_FILE"
    ok "installed $CRON_FILE (every $EVERY minute(s))"
  elif [[ -d /run/systemd/system && -w "$UNIT_DIR" ]] && command -v systemctl >/dev/null; then
    printf '[Unit]\nDescription=Glasshaus upgrade helper\n\n[Service]\nType=oneshot\nExecStart=%s --every %s\n' \
      "$self" "$EVERY" > "$UNIT_DIR/$UNIT.service"
    printf '[Unit]\nDescription=Run the Glasshaus upgrade helper every %s minute(s)\n\n[Timer]\nOnCalendar=*:0/%s\nAccuracySec=5s\n\n[Install]\nWantedBy=timers.target\n' \
      "$EVERY" "$EVERY" > "$UNIT_DIR/$UNIT.timer"
    systemctl daemon-reload
    systemctl enable --now "$UNIT.timer" >/dev/null
    ok "installed the $UNIT.timer systemd timer (every $EVERY minute(s))"
  else
    warn "no cron (/etc/cron.d) or systemd found, or not running as root"
    print_schedule "$self"
  fi
  "$self"  # check in now
}

uninstall_schedule() {
  local removed=0
  if [[ -f "$CRON_FILE" ]]; then rm -f "$CRON_FILE"; removed=1; fi
  if [[ -f "$UNIT_DIR/$UNIT.timer" ]]; then
    systemctl disable --now "$UNIT.timer" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$UNIT.timer" "$UNIT_DIR/$UNIT.service"
    systemctl daemon-reload 2>/dev/null || true
    removed=1
  fi
  if [[ "$removed" == 1 ]]; then ok "removed the upgrade helper schedule"; else info "no schedule installed here"; fi
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
  local action=run
  while (( $# )); do
    case "$1" in
      --install) action=install ;;
      --print) action=print ;;
      --uninstall) action=uninstall ;;
      --every)
        EVERY="${2:-}"
        [[ "$EVERY" =~ ^(1|2|3|4|5|6|10|12|15|20|30)$ ]] || die "--every must be 1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30 (minutes)"
        shift ;;
      *) die "unknown option: $1 (use --install, --print, --uninstall or --every N)" ;;
    esac
    shift
  done
  case "$action" in
    install | print) install_schedule "$action"; return ;;
    uninstall) uninstall_schedule; return ;;
  esac
  EVERY="${EVERY:-1}"
  [[ "$(id -u)" == 0 ]] || die "run as root (update.sh needs Docker)"
  [[ -f "$ENV_FILE" ]] || die ".env not found; run ./setup.sh first"
  local dir
  dir="$(upgrade_dir)"
  ensure_upgrade_dir
  exec 9>"$dir/.lock"
  flock -n 9 || exit 0  # an upgrade is already running
  write_json "$dir/agent.json" last_seen "$(now)" helper "1" every_minutes "$EVERY"

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
  write_json "$dir/agent.json" last_seen "$(now)" helper "1" every_minutes "$EVERY"
}

main "$@"
