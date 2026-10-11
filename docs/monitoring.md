# Health and monitoring

Glasshaus watches itself. Every five minutes the worker checks everything it depends on, and you can see
the result three ways: **Admin → System status**, alerts to owners and admins, and Prometheus gauges on
`/metrics`. Like backups and upgrades, this is server-wide, so the page and alerts are only offered when
the server hosts a single organization.

## What is checked

| Check | Warning | Problem |
| --- | --- | --- |
| Database | more than 80 % of connections in use | can't connect |
| Redis | more than 90 % of `maxmemory` in use | can't connect |
| Background worker | no check-in for 2 minutes | no check-in for 3 minutes |
| Job queue | more than 100 jobs waiting | more than 1,000 jobs waiting |
| Live updates and integrations | a change waiting over 5 minutes | a change waiting over 30 minutes |
| Slack, Teams and webhooks | a message gave up in the last 24 hours | — |
| Backups | see [Backup and restore](../README.md#backup-and-restore) | no backup, an old backup, or a failed restore drill |
| Disk space (backup disk) | under 15 % free | under 5 % free |
| Version | — (shows when a new release is out) | — |

Backups and disk space appear when the backup folder is mounted (`GLASSHAUS_BACKUP_STATUS_DIR`, set by
`docker-compose.yml`).

## Alerts

When a check needs attention, owners and admins get an in-app notification (and an email when
[email](reports.md) is set up) that links to Admin → System status. Each problem alerts at most once every
six hours while it lasts. Backups already alert once a day on their own, so they are not repeated here.

The worker can't report its own death, so the API watches the worker's heartbeat as well and raises the
"Background worker" alert if it stops.

## Prometheus

`/metrics` is on the API port (`http://<host>:8471/metrics`, bound to `127.0.0.1` by default). It
includes request counts and latency (shared across all API processes) and, from the worker's latest
check:

| Metric | Meaning |
| --- | --- |
| `glasshaus_build_info{version}` | Always 1; the running version |
| `glasshaus_status_age_seconds` | Age of the latest check (should stay under 600) |
| `glasshaus_check_state{check}` | 0 ok, 1 unknown, 2 warning, 3 problem |
| `glasshaus_database_size_bytes`, `glasshaus_database_connections` | Database |
| `glasshaus_redis_memory_bytes` | Redis |
| `glasshaus_worker_heartbeat_age_seconds` | Seconds since the worker checked in |
| `glasshaus_queue_jobs` | Background jobs waiting |
| `glasshaus_events_unpublished`, `glasshaus_events_oldest_unpublished_seconds` | Changes not yet delivered |
| `glasshaus_integration_failures_24h`, `glasshaus_integration_retrying` | Integrations |
| `glasshaus_backup_newest_age_seconds`, `glasshaus_backups`, `glasshaus_backup_drill_ok` | Backups |
| `glasshaus_disk_free_bytes`, `glasshaus_disk_free_ratio` | Backup disk |
| `glasshaus_update_available` | 1 when a newer release is out |

To scrape from another host, set `GLASSHAUS_API_BIND_ADDRESS` to an address that host can reach and set
`GLASSHAUS_METRICS_TOKEN` to a long random string; `/metrics` then needs it as a bearer token:

```yaml
scrape_configs:
  - job_name: glasshaus
    scrape_interval: 60s
    authorization: { credentials: "<GLASSHAUS_METRICS_TOKEN>" }
    static_configs: [{ targets: ["truenas.lan:8471"] }]
```

Example alert rules:

```yaml
groups:
  - name: glasshaus
    rules:
      - alert: GlasshausDown
        expr: up{job="glasshaus"} == 0
        for: 5m
      - alert: GlasshausCheckFailing
        expr: glasshaus_check_state >= 3
        for: 10m
        annotations: { summary: "Glasshaus {{ $labels.check }} has a problem" }
      - alert: GlasshausStatusStale
        expr: glasshaus_status_age_seconds > 900
        annotations: { summary: "The Glasshaus worker has stopped checking" }
      - alert: GlasshausSlowRequests
        expr: histogram_quantile(0.95, sum by (le) (rate(glasshaus_http_request_duration_seconds_bucket[5m]))) > 1
        for: 15m
```

Uptime Kuma and similar tools can poll `/readyz` on the web port (`http://<host>:8470/readyz`, 200 when
the database and Redis are reachable).
