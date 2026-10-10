#!/bin/sh
# Scheduled PostgreSQL backups (runs inside the `backup` service). Custom-format dumps, encrypted with
# age when BACKUP_KEY is set (the default; setup.sh/update.sh generate it), each with a SHA-256 file,
# pruned by age.
set -eu
interval_hours="${BACKUP_INTERVAL_HOURS:-24}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
drill_days="${BACKUP_DRILL_DAYS:-7}"  # 0 turns the restore drill off
umask 077  # the whole database: only the backup service reads dumps (the app only lists them)

while true; do
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  recipient=""
  if [ -n "${BACKUP_KEY:-}" ]; then
    name="glasshaus-${ts}.dump.age"
    recipient="$(printf '%s\n' "$BACKUP_KEY" | age-keygen -y 2>/dev/null)" \
      || echo "backup: BACKUP_KEY is not a valid age key (AGE-SECRET-KEY-…)" >&2
  else
    name="glasshaus-${ts}.dump"
    echo "backup: BACKUP_KEY is not set; writing an unencrypted dump" >&2
  fi
  out="/backups/${name}"
  rm -f /tmp/pg_dump.failed
  if [ -n "${BACKUP_KEY:-}" ]; then
    if [ -z "$recipient" ] \
      || ! { pg_dump --format=custom --no-owner || touch /tmp/pg_dump.failed; } | age -r "$recipient" -o "${out}.partial"; then
      touch /tmp/pg_dump.failed
    fi
  else
    pg_dump --format=custom --no-owner --file="${out}.partial" || touch /tmp/pg_dump.failed
  fi
  if [ ! -e /tmp/pg_dump.failed ] && [ -s "${out}.partial" ]; then
    mv "${out}.partial" "${out}"
    (cd /backups && sha256sum "${name}" > "${name}.sha256")
    chmod 644 "${out}.sha256"  # the checksum reveals nothing; the app shows whether it is there
    echo "backup: wrote ${out}"
    # Restore drill: prove a backup restores, at most every drill_days days.
    if [ "$drill_days" -gt 0 ] && [ -z "$(find /backups -maxdepth 1 -name drill-status.json -mtime "-${drill_days}" 2>/dev/null)" ]; then
      /bin/sh /scripts/restore-drill.sh "${out}" || true
    fi
  else
    rm -f "${out}.partial"
    echo "backup: FAILED at ${ts}" >&2
  fi
  find /backups -maxdepth 1 \( -name 'glasshaus-*.dump' -o -name 'glasshaus-*.dump.age' -o -name 'glasshaus-*.sha256' \) \
    -type f -mtime "+${retention_days}" -print -delete
  sleep "$((interval_hours * 3600))"
done
