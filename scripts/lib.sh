#!/usr/bin/env bash
# Shared helpers for setup.sh, update.sh and scripts/*. Source, don't execute.
# shellcheck disable=SC2034

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
APP_SERVICES=(api worker mcp web)

if [[ -t 1 ]]; then C_INFO=$'\e[36m'; C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_END=$'\e[0m'
else C_INFO=; C_OK=; C_WARN=; C_ERR=; C_END=; fi
info() { printf '%s==>%s %s\n' "$C_INFO" "$C_END" "$*"; }
ok()   { printf '%s ok%s %s\n' "$C_OK" "$C_END" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_WARN" "$C_END" "$*" >&2; }
die()  { printf '%serror%s %s\n' "$C_ERR" "$C_END" "$*" >&2; exit 1; }

# Honours docker-compose.override.yml (gitignored) like plain `docker compose` does.
compose() {
  local files=(-f "$ROOT_DIR/docker-compose.yml")
  [[ -f "$ROOT_DIR/docker-compose.override.yml" ]] && files+=(-f "$ROOT_DIR/docker-compose.override.yml")
  docker compose --project-directory "$ROOT_DIR" "${files[@]}" "$@"
}

# get_env KEY -> value from .env (empty if missing)
get_env() {
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v k="$1" '$1 == k { sub(/^[^=]*=/, ""); v = $0 } END { print v }' "$ENV_FILE"
}

# set_env KEY VALUE -> replace or append in .env (portable; no sed -i)
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  awk -F= -v k="$key" -v v="$value" '
    $1 == k { print k "=" v; found = 1; next } { print }
    END { if (!found) print k "=" v }' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex "${1:-32}"
  else head -c "${1:-32}" /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

# wait_healthy TIMEOUT_SECONDS SERVICE... -> 0 once every service reports healthy
wait_healthy() {
  local timeout="$1"; shift
  local deadline=$((SECONDS + timeout)) svc cid status pending
  while (( SECONDS < deadline )); do
    pending=()
    for svc in "$@"; do
      cid="$(compose ps -q "$svc" 2>/dev/null)"
      status="$( [[ -n "$cid" ]] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null)"
      [[ "$status" == "healthy" ]] || pending+=("$svc:${status:-missing}")
    done
    (( ${#pending[@]} == 0 )) && return 0
    sleep 3
  done
  warn "not healthy after ${timeout}s: ${pending[*]}"
  return 1
}

# backup_now LABEL -> path of a custom-format pg_dump in the backup dir
backup_now() {
  local dir label="$1" ts out
  dir="$(get_env GLASSHAUS_BACKUP_DIR)"; dir="${dir:-./backups}"
  [[ "$dir" = /* ]] || dir="$ROOT_DIR/${dir#./}"
  mkdir -p "$dir"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  out="$dir/glasshaus-${label}-${ts}.dump"
  compose exec -T postgres pg_dump -U glasshaus -d glasshaus --format=custom --no-owner > "$out.partial" \
    || { rm -f "$out.partial"; return 1; }
  mv "$out.partial" "$out"
  printf '%s\n' "$out"
}

# restore_dump FILE -> replace database contents with a dump (app services are stopped first)
restore_dump() {
  local dump="$1"
  [[ -s "$dump" ]] || die "backup not found or empty: $dump"
  compose stop "${APP_SERVICES[@]}" >/dev/null 2>&1 || true
  compose exec -T postgres psql -U glasshaus -d postgres -v ON_ERROR_STOP=1 -q \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'glasshaus' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS glasshaus;" -c "CREATE DATABASE glasshaus OWNER glasshaus;" >/dev/null
  compose exec -T postgres pg_restore -U glasshaus -d glasshaus --no-owner --exit-on-error < "$dump"
}
