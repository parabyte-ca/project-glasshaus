#!/usr/bin/env bash
# On-demand database backup: scripts/backup.sh [label]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
out="$(backup_now "${1:-manual}")"
ok "backup written: $out"
