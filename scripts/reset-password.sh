#!/usr/bin/env bash
# Set a new password for a person from the server, when nobody can sign in to reset it in the app:
#   sudo ./scripts/reset-password.sh [email]      (default: GLASSHAUS_ADMIN_EMAIL from .env)
# It asks for the new password (12+ characters), ends their other sign-ins and clears any sign-in lockout.
# Editing GLASSHAUS_ADMIN_PASSWORD in .env does nothing once the first owner exists; use this instead.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
email="${1:-$(get_env GLASSHAUS_ADMIN_EMAIL)}"
[[ -n "$email" ]] || die "usage: scripts/reset-password.sh <email>"
compose ps --status running --services 2>/dev/null | grep -qx api || die "the stack is not running; start it with 'docker compose up -d'"
compose exec api glasshaus reset-password "$email"
