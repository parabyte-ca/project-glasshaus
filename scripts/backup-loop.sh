#!/bin/sh
# Scheduled PostgreSQL backups (runs inside the `backup` service). Custom-format dumps, pruned by age.
set -eu
interval_hours="${BACKUP_INTERVAL_HOURS:-24}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
drill_days="${BACKUP_DRILL_DAYS:-7}"  # 0 turns the restore drill off

while true; do
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  out="/backups/glasshaus-${ts}.dump"
  if pg_dump --format=custom --no-owner --file="${out}.partial"; then
    mv "${out}.partial" "${out}"
    echo "backup: wrote ${out}"
    # Restore drill: prove a backup restores, at most every drill_days days.
    if [ "$drill_days" -gt 0 ] && [ -z "$(find /backups -maxdepth 1 -name drill-status.json -mtime "-${drill_days}" 2>/dev/null)" ]; then
      /bin/sh /scripts/restore-drill.sh "${out}" || true
    fi
  else
    rm -f "${out}.partial"
    echo "backup: FAILED at ${ts}" >&2
  fi
  find /backups -name 'glasshaus-*.dump' -type f -mtime "+${retention_days}" -print -delete
  sleep "$((interval_hours * 3600))"
done
