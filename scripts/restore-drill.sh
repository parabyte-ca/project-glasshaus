#!/bin/sh
# Restore drill: restore a backup into a scratch database, check it, drop it, and record the result in
# /backups/drill-status.json (shown in Admin > Backups). Runs inside the `backup` service:
#   docker compose exec backup /bin/sh /scripts/restore-drill.sh [/backups/<file>.dump]
# With no file, the newest backup is used. Exit status 0 = the backup restored and looks complete.
set -u
umask 022  # readable by the app (Admin > Backups), writable only by the backup service
status=/backups/drill-status.json
db=glasshaus_drill
started="$(date +%s)"
# shellcheck disable=SC2012  # our own timestamped names; newest first
dump="${1:-$(ls -1t /backups/glasshaus-*.dump 2>/dev/null | head -n 1)}"
tables=0 revision="" live_revision="" users=0 projects=0 tasks=0

clean() { printf '%s' "$1" | tr -d '\042\134' | tr '\n\r\t' '   ' | cut -c1-300; }

write() {  # write OK ERROR
  bytes=0
  [ -f "$dump" ] && bytes="$(wc -c < "$dump" | tr -d ' ')"
  cat > "$status.tmp" <<JSON
{"finished_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "ok": $1, "dump": "$(clean "$(basename "${dump:-none}")")", "dump_bytes": $bytes, "seconds": $(( $(date +%s) - started )), "tables": ${tables:-0}, "revision": "$(clean "$revision")", "live_revision": "$(clean "$live_revision")", "rows": {"users": ${users:-0}, "projects": ${projects:-0}, "tasks": ${tasks:-0}}, "error": "$(clean "$2")"}
JSON
  mv "$status.tmp" "$status"
}

fail() {
  dropdb --if-exists "$db" >/dev/null 2>&1
  write false "$1"
  echo "drill: FAILED: $1" >&2
  exit 1
}

count() { psql -d "$db" -tAc "$1" 2>/dev/null | tr -d ' '; }

[ -n "$dump" ] && [ -s "$dump" ] || fail "no backup file found"
dropdb --if-exists "$db" >/dev/null 2>&1
createdb "$db" || fail "could not create the scratch database"
if ! pg_restore --no-owner --exit-on-error -d "$db" "$dump" 2>/tmp/drill.err; then
  fail "pg_restore failed: $(tail -n 1 /tmp/drill.err)"
fi
tables="$(count "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
revision="$(count "SELECT version_num FROM alembic_version")"
live_revision="$(psql -tAc "SELECT version_num FROM alembic_version" 2>/dev/null | tr -d ' ')"
users="$(count "SELECT count(*) FROM users")"
projects="$(count "SELECT count(*) FROM projects")"
tasks="$(count "SELECT count(*) FROM tasks")"
[ -n "$revision" ] || fail "the restored database has no schema version"
[ "${users:-0}" -gt 0 ] || fail "the restored database has no users"
dropdb "$db" || fail "could not drop the scratch database"
write true ""
echo "drill: ok ($(basename "$dump"): $tables tables, $users users, $projects projects, $tasks tasks)"
