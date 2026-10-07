#!/usr/bin/env bash
# Project Glasshaus first-run installer. Idempotent: safe to re-run at any time.
#   ./setup.sh [--demo] [--pull] [--no-start]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/scripts/lib.sh"
cd "$ROOT_DIR"

DEMO=0 PULL=0 START=1
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=1 ;;
    --pull) PULL=1 ;;
    --no-start) START=0 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

info "Checking prerequisites"
command -v docker >/dev/null || die "Docker is required: https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "Docker daemon is not reachable (is it running, and can $(id -un) use it?)"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is required"
compose_ver="$(docker compose version --short | sed 's/^v//')"
[[ "${compose_ver%%.*}" -ge 2 ]] || die "Docker Compose >= 2.20 required (found $compose_ver)"
ok "docker $(docker version -f '{{.Server.Version}}'), compose $compose_ver"

info "Preparing configuration"
if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "created .env from .env.example"
fi
ensure_secrets
set_env GLASSHAUS_VERSION "$(tr -d '[:space:]' < VERSION)"
set_env GLASSHAUS_BUILD_SHA "$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
set_env GLASSHAUS_BACKUP_UID "$(id -u)"
set_env GLASSHAUS_BACKUP_GID "$(id -g)"
backup_dir="$(get_env GLASSHAUS_BACKUP_DIR)"; mkdir -p "${backup_dir:-./backups}"

info "Checking host ports"
for var in GLASSHAUS_WEB_PORT GLASSHAUS_API_PORT GLASSHAUS_MCP_PORT; do
  port="$(get_env "$var")"
  if command -v ss >/dev/null && ss -ltnH "sport = :$port" 2>/dev/null | grep -q . \
     && ! compose ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$port->"; then
    warn "port $port ($var) is in use by another process; change it in .env"
  fi
done

if [[ "$PULL" == 1 ]]; then
  info "Pulling images"; compose pull || die "image pull failed (run without --pull to build locally)"
else
  info "Building images"; compose build
fi

[[ "$START" == 1 ]] || { ok "configuration ready; start with: docker compose up -d"; exit 0; }

info "Starting stack (migrations run automatically)"
compose up -d --remove-orphans || { compose logs --tail 50 migrate; die "stack failed to start"; }
wait_healthy 180 api worker mcp web || { compose logs --tail 50 migrate api; die "stack failed to become healthy"; }

if [[ "$DEMO" == 1 ]]; then
  info "Generating demo data"; compose run --rm --no-deps migrate glasshaus seed --demo
fi

ok "Project Glasshaus $(get_env GLASSHAUS_VERSION) is running"
public="$(get_env GLASSHAUS_PUBLIC_URL)"
cat <<MSG
  Web UI : ${public:-http://localhost:$(get_env GLASSHAUS_WEB_PORT)}
  API    : http://localhost:$(get_env GLASSHAUS_API_PORT)/api/docs
  MCP    : http://localhost:$(get_env GLASSHAUS_MCP_PORT)/mcp
  Sign in: $(get_env GLASSHAUS_ADMIN_EMAIL) (password: GLASSHAUS_ADMIN_PASSWORD in .env — change it after first login)
MSG
