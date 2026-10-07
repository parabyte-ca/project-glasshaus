#!/usr/bin/env bash
# Restore the database from a pg_dump custom-format file: scripts/restore.sh <file.dump> [--yes]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
dump="${1:?usage: scripts/restore.sh <file.dump> [--yes]}"
if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "This REPLACES all Glasshaus data with $(basename "$dump"). Type 'restore' to continue: " answer
  [[ "$answer" == "restore" ]] || die "aborted"
fi
safety="$(backup_now pre-restore)" && ok "safety backup: $safety"
restore_dump "$dump"
compose up -d
wait_healthy 180 api worker mcp web && ok "restored from $dump"
