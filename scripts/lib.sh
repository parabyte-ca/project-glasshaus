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
  # GLASSHAUS_COMPOSE_FILE lets update.sh roll back with the previous release's compose file.
  local files=(-f "${GLASSHAUS_COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}")
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

# ensure_secrets -> generate any missing secret in .env (idempotent; used by setup.sh and update.sh)
ensure_secrets() {
  local spec name
  for spec in GLASSHAUS_SECRET_KEY:48 POSTGRES_PASSWORD:24 POSTGRES_APP_PASSWORD:24 REDIS_PASSWORD:24 \
              GLASSHAUS_ADMIN_PASSWORD:12; do
    name="${spec%%:*}"
    if [[ -z "$(get_env "$name")" ]]; then
      set_env "$name" "$(gen_secret "${spec##*:}")"
      ok "generated $name"
    fi
  done
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

# age_in_backup SCRIPT -> run a shell snippet in the backup image (it has age; the host needs nothing).
# stdin and stdout pass through; the key reaches the container through the environment only.
age_in_backup() {
  BACKUP_KEY="$(get_env GLASSHAUS_BACKUP_KEY)" \
    compose run --rm --no-deps -T -e BACKUP_KEY --entrypoint /bin/sh backup -c "$1"
}

# backup_image_ready -> 0 when the backup image for the running release exists (and so has age)
backup_image_ready() {
  local image
  image="$(compose config --images 2>/dev/null | grep -m 1 /glasshaus-backup:)"
  [[ -n "$image" ]] && docker image inspect "$image" >/dev/null 2>&1 \
    && compose run --rm --no-deps -T --entrypoint age backup --version >/dev/null 2>&1
}

# ensure_backup_key -> generate the age key that encrypts backups, once (setup.sh and update.sh)
# upgrade_dir -> the host folder shared with the API for upgrades started in Admin > Updates.
upgrade_dir() {
  local dir
  dir="$(get_env GLASSHAUS_UPGRADE_FOLDER)"
  dir="${dir:-./upgrade}"
  [[ "$dir" == /* ]] || dir="$ROOT_DIR/${dir#./}"
  printf '%s\n' "$dir"
}

# ensure_upgrade_dir -> create the upgrade folder, writable by the app (uid 10001) and root only.
ensure_upgrade_dir() {
  local dir
  dir="$(upgrade_dir)"
  mkdir -p "$dir"
  if [[ "$(id -u)" == 0 ]]; then
    chown 10001:10001 "$dir" && chmod 0770 "$dir"
  fi
}

ensure_backup_key() {
  [[ -n "$(get_env GLASSHAUS_BACKUP_KEY)" ]] && return 0
  local key
  key="$(compose run --rm --no-deps -T --entrypoint age-keygen backup 2>/dev/null | grep '^AGE-SECRET-KEY-')" \
    || { warn "could not generate a backup key; backups stay unencrypted"; return 0; }
  set_env GLASSHAUS_BACKUP_KEY "$key"
  ok "generated GLASSHAUS_BACKUP_KEY: backups are now encrypted"
  warn "copy GLASSHAUS_BACKUP_KEY from .env to a password manager; encrypted backups cannot be restored without it"
}

# write_checksum FILE -> FILE.sha256 next to it (sha256sum -c format)
write_checksum() {
  command -v sha256sum >/dev/null 2>&1 || return 0
  (cd "$(dirname "$1")" && sha256sum "$(basename "$1")" > "$(basename "$1").sha256")
}

# dump_stream FILE -> the pg_dump on stdout: checksum checked, decrypted when it is a .age file
dump_stream() {
  local dump="$1"
  [[ -s "$dump" ]] || die "backup not found or empty: $dump"
  if [[ -f "$dump.sha256" ]] && command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "$dump")" && sha256sum -c --status "$(basename "$dump").sha256") \
      || die "checksum mismatch: $dump is damaged"
  fi
  case "$dump" in
    *.age)
      [[ -n "$(get_env GLASSHAUS_BACKUP_KEY)" ]] || die "$dump is encrypted: set GLASSHAUS_BACKUP_KEY in .env"
      # shellcheck disable=SC2016  # expanded inside the backup container
      age_in_backup 'k="$(mktemp)"; printf "%s\n" "$BACKUP_KEY" > "$k"; age -d -i "$k"; rc=$?; rm -f "$k"; exit $rc' \
        < "$dump" ;;
    *) cat "$dump" ;;
  esac
}

# backup_now LABEL -> path of a custom-format pg_dump in the backup dir (encrypted .dump.age when a
# backup key is set and the backup image is available), with a .sha256 next to it
backup_now() {
  local dir label="$1" ts out
  dir="$(get_env GLASSHAUS_BACKUP_DIR)"; dir="${dir:-./backups}"
  [[ "$dir" = /* ]] || dir="$ROOT_DIR/${dir#./}"
  mkdir -p "$dir"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  out="$dir/glasshaus-${label}-${ts}.dump"
  if [[ -n "$(get_env GLASSHAUS_BACKUP_KEY)" ]] && backup_image_ready; then
    out="$out.age"
    # shellcheck disable=SC2016  # expanded inside the backup container
    (set -o pipefail; umask 077 \
      && compose exec -T postgres pg_dump -U glasshaus -d glasshaus --format=custom --no-owner \
      | age_in_backup 'age -r "$(printf "%s\n" "$BACKUP_KEY" | age-keygen -y)"' > "$out.partial") \
      || { rm -f "$out.partial"; return 1; }
  else
    (umask 077 && compose exec -T postgres pg_dump -U glasshaus -d glasshaus --format=custom --no-owner \
      > "$out.partial") || { rm -f "$out.partial"; return 1; }
  fi
  [[ -s "$out.partial" ]] || { rm -f "$out.partial"; return 1; }
  mv "$out.partial" "$out"
  write_checksum "$out"
  printf '%s\n' "$out"
}

# restore_dump FILE -> replace database contents with a dump (app services are stopped first)
restore_dump() {
  local dump="$1"
  [[ -s "$dump" ]] || die "backup not found or empty: $dump"
  dump_stream "$dump" > /dev/null || die "cannot read $dump"  # checksum and key, before anything stops
  compose stop "${APP_SERVICES[@]}" >/dev/null 2>&1 || true
  compose exec -T postgres psql -U glasshaus -d postgres -v ON_ERROR_STOP=1 -q \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'glasshaus' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS glasshaus;" -c "CREATE DATABASE glasshaus OWNER glasshaus;" >/dev/null
  dump_stream "$dump" | compose exec -T postgres pg_restore -U glasshaus -d glasshaus --no-owner --exit-on-error
}

# preflight_check DUMP -> 0 when the release in .env migrates a copy of DUMP and its API becomes ready.
# Uses a scratch database and Redis database 15; the running services are not touched.
preflight_check() {
  local dump="$1" db=glasshaus_preflight name="glasshaus-preflight-$$" deadline status="" rc=1
  local owner app redis
  owner="postgresql+asyncpg://glasshaus:$(get_env POSTGRES_PASSWORD)@postgres:5432/${db}"
  app="postgresql+asyncpg://glasshaus_app:$(get_env POSTGRES_APP_PASSWORD)@postgres:5432/${db}"
  redis="redis://:$(get_env REDIS_PASSWORD)@redis:6379/15"
  info "Pre-flight: trying the new release on a copy of the database"
  _pf_cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    compose exec -T postgres dropdb -U glasshaus --if-exists "$db" >/dev/null 2>&1 || true
  }
  _pf_cleanup
  # Values reach the containers through the environment (-e NAME), never on the command line.
  if compose exec -T postgres createdb -U glasshaus "$db" \
    && dump_stream "$dump" | compose exec -T postgres pg_restore -U glasshaus -d "$db" --no-owner --exit-on-error \
    && GLASSHAUS_DATABASE_URL="$app" GLASSHAUS_MIGRATION_DATABASE_URL="$owner" \
       compose run --rm --no-deps -T -e GLASSHAUS_DATABASE_URL -e GLASSHAUS_MIGRATION_DATABASE_URL \
         migrate glasshaus migrate; then
    GLASSHAUS_DATABASE_URL="$app" GLASSHAUS_REDIS_URL="$redis" \
      compose run -d --no-deps --name "$name" -e GLASSHAUS_DATABASE_URL -e GLASSHAUS_REDIS_URL api >/dev/null || true
    # Ask the API itself: Docker's health status can read "unhealthy" while a slow host is still
    # starting the worker processes. Give up early only if the container stops.
    deadline=$((SECONDS + ${GLASSHAUS_PREFLIGHT_TIMEOUT:-240}))
    while (( SECONDS < deadline )); do
      status="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)"
      [[ "$status" == "exited" || "$status" == "dead" || -z "$status" ]] && break
      if docker exec "$name" python -c \
        "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).status == 200 else 1)" \
        >/dev/null 2>&1; then
        rc=0; break
      fi
      sleep 3
    done
    if (( rc != 0 )); then
      warn "the new API did not become ready on the copy within ${GLASSHAUS_PREFLIGHT_TIMEOUT:-240}s (state: ${status:-missing})"
      docker logs --tail 40 "$name" >&2 2>&1 || true
    fi
  else
    warn "the new release could not migrate a copy of the database"
  fi
  _pf_cleanup
  return "$rc"
}
