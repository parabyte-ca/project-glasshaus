#!/usr/bin/env bash
# Restore the database from a backup: scripts/restore.sh <file.dump|file.dump.age> [--yes]
# Encrypted backups (.dump.age) need GLASSHAUS_BACKUP_KEY in .env; a .sha256 next to the file is checked.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
dump="${1:?usage: scripts/restore.sh <file.dump|file.dump.age> [--yes]}"
if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "This REPLACES all Glasshaus data with $(basename "$dump"). Type 'restore' to continue: " answer
  [[ "$answer" == "restore" ]] || die "aborted"
fi
safety="$(backup_now pre-restore)" && ok "safety backup: $safety"
restore_dump "$dump"
compose up -d
wait_healthy 180 api worker mcp web && ok "restored from $dump"
