"""System status: is everything Glasshaus depends on working, and is anything falling behind?

``collect()`` runs a set of checks (database, Redis, the worker, the job queue, event delivery,
integrations, backups, disk space, updates). They feed three things:

- **Admin > System status**, for owners and admins (single-organization servers, like backups);
- **Prometheus gauges** on ``/metrics`` (from the latest snapshot the worker stores every few minutes);
- **alerts**: the worker checks every five minutes and notifies owners and admins (in the app, and by
  email when it is set up) at most every six hours per problem. The worker can't report its own death,
  so the API watches the worker's heartbeat and raises that alert.
"""

import asyncio
import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import func, select, text

from glasshaus import mail
from glasshaus.collab.models import NotificationKind
from glasshaus.collab.service import notify_users
from glasshaus.config import get_settings
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import NotFound, ServiceError
from glasshaus.core.rbac import ORG_ADMIN_ROLES, Permission
from glasshaus.core.schemas import Schema
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.logs import get_logger
from glasshaus.models.tenant import Tenant
from glasshaus.redis_client import get_redis
from glasshaus.version import __version__

log = get_logger(__name__)
LINK = "/admin?tab=status"
SNAPSHOT_KEY = "glasshaus:status:snapshot"
WATCHDOG_KEY = "glasshaus:status:watchdog"
HEARTBEAT_KEY = "glasshaus:worker:heartbeat"  # written by the worker every 30 seconds
ARQ_QUEUE = "arq:queue"
ALERT_EVERY = timedelta(hours=6)
# Backups already alert on their own (glasshaus.backups.watch), and updates are good news.
NO_ALERT = {"backups", "updates"}

State = Literal["ok", "warning", "critical", "unknown"]
RANK = {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}


class Check(Schema):
    key: str
    name: str
    state: State
    message: str
    metrics: dict[str, float] = Field(default_factory=dict, description="Numbers behind the check.")


class SystemStatus(Schema):
    checked_at: datetime
    overall: State
    version: str
    checks: list[Check]


def _check(key: str, name: str, state: State, message: str, **metrics: float) -> Check:
    return Check(key=key, name=name, state=state, message=message, metrics=metrics)


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"  # pragma: no cover


async def _database() -> Check:
    try:
        async with system_session() as session:
            size = await session.scalar(text("SELECT pg_database_size(current_database())"))
            used = await session.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            )
            limit = await session.scalar(text("SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"))
    except Exception as exc:  # noqa: BLE001 - any failure means the database is not usable
        return _check("database", "Database", "critical", f"Can't reach the database ({type(exc).__name__}).")
    ratio = (used or 0) / (limit or 100)
    state: State = "warning" if ratio > 0.8 else "ok"
    message = f"{_size(size or 0)}, {used} of {limit} connections in use."
    return _check("database", "Database", state, message, size_bytes=size or 0, connections=used or 0)


async def _redis() -> Check:
    try:
        info = await asyncio.wait_for(get_redis().info("memory"), timeout=3)
    except Exception as exc:  # noqa: BLE001
        return _check("redis", "Redis", "critical", f"Can't reach Redis ({type(exc).__name__}).")
    used = float(info.get("used_memory", 0))
    limit = float(info.get("maxmemory", 0))
    state: State = "warning" if limit and used / limit > 0.9 else "ok"
    message = f"{_size(used)} in use" + (f" of {_size(limit)}." if limit else ".")
    return _check("redis", "Redis", state, message, memory_bytes=used)


async def _worker(now: datetime) -> Check:
    try:
        raw = await get_redis().get(HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001 - Redis is reported by its own check
        return _check("worker", "Background worker", "unknown", "Can't tell: Redis is not reachable.")
    if not raw:
        return _check(
            "worker",
            "Background worker",
            "critical",
            "The worker hasn't checked in for over 3 minutes: notifications, emails, automations and "
            "scheduled jobs are not running.",
        )
    seen = datetime.fromisoformat(raw)
    age = max(0.0, (now - seen).total_seconds())
    state: State = "warning" if age > 120 else "ok"
    return _check("worker", "Background worker", state, f"Last checked in {int(age)} s ago.", heartbeat_age_seconds=age)


async def _queue() -> Check:
    try:
        waiting = int(await get_redis().zcard(ARQ_QUEUE))
    except Exception:  # noqa: BLE001
        return _check("queue", "Job queue", "unknown", "Can't tell: Redis is not reachable.")
    state: State = "critical" if waiting > 1000 else "warning" if waiting > 100 else "ok"
    message = "No jobs waiting." if waiting == 0 else f"{waiting} jobs waiting."
    return _check("queue", "Job queue", state, message, jobs=waiting)


async def _events(now: datetime) -> Check:
    from glasshaus.core.models import DomainEventRecord

    try:
        async with system_session() as session:
            row = (
                await session.execute(
                    select(func.count(), func.min(DomainEventRecord.occurred_at)).where(
                        DomainEventRecord.published_at.is_(None)
                    )
                )
            ).one()
    except Exception:  # noqa: BLE001
        return _check("events", "Live updates and integrations", "unknown", "Can't tell: the database is not reachable.")
    count, oldest = int(row[0]), row[1]
    age = (now - oldest).total_seconds() if oldest else 0.0
    state: State = "critical" if age > 1800 else "warning" if age > 300 else "ok"
    message = (
        "Every change has been delivered."
        if count == 0
        else f"{count} changes waiting to be delivered; the oldest is {int(age // 60)} min old."
    )
    return _check("events", "Live updates and integrations", state, message, unpublished=count, oldest_seconds=age)


async def _integrations(now: datetime) -> Check:
    from glasshaus.integrations.models import IntegrationDelivery

    since = now - timedelta(hours=24)
    try:
        async with system_session() as session:
            failed = int(
                await session.scalar(
                    select(func.count()).where(
                        IntegrationDelivery.status == "failed", IntegrationDelivery.created_at >= since
                    )
                )
                or 0
            )
            retrying = int(
                await session.scalar(
                    select(func.count()).where(
                        IntegrationDelivery.status == "pending", IntegrationDelivery.attempts > 0
                    )
                )
                or 0
            )
    except Exception:  # noqa: BLE001
        return _check("integrations", "Slack, Teams and webhooks", "unknown", "Can't tell: the database is not reachable.")
    state: State = "warning" if failed else "ok"
    message = (
        f"{failed} messages gave up in the last 24 hours (see Admin > Integrations)."
        if failed
        else "All messages delivered."
    ) + (f" {retrying} being retried." if retrying else "")
    return _check("integrations", "Slack, Teams and webhooks", state, message, failed_24h=failed, retrying=retrying)


def _backups(now: datetime) -> Check | None:
    from glasshaus import backups

    if not get_settings().backup_status_dir:
        return None
    found = backups.status(now)
    if not found.available:
        return _check("backups", "Backups", "unknown", "The backup folder is not visible to Glasshaus.")
    newest = found.latest[0] if found.latest else None
    age = (now - newest.created_at).total_seconds() if newest else -1.0
    metrics: dict[str, float] = {"newest_age_seconds": age, "count": found.count}
    if found.drill is not None:
        metrics["drill_ok"] = 1.0 if found.drill.ok else 0.0
    if found.problems:
        return Check(
            key="backups",
            name="Backups",
            state="critical" if any(p.code in ("backup_missing", "drill_failed") for p in found.problems) else "warning",
            message=" ".join(p.message for p in found.problems),
            metrics=metrics,
        )
    return Check(key="backups", name="Backups", state="ok", message="Up to date; the last restore drill passed.", metrics=metrics)


def _disk() -> Check | None:
    folder = get_settings().backup_status_dir
    if not folder:
        return None
    try:
        usage = shutil.disk_usage(folder)
    except OSError:
        return _check("disk", "Disk space", "unknown", "Can't read the backup disk.")
    ratio = usage.free / usage.total if usage.total else 1.0
    state: State = "critical" if ratio < 0.05 else "warning" if ratio < 0.15 else "ok"
    message = f"{_size(usage.free)} free of {_size(usage.total)} ({ratio:.0%}) on the backup disk."
    return _check("disk", "Disk space", state, message, free_bytes=usage.free, free_ratio=round(ratio, 4))


async def _updates() -> Check:
    from glasshaus import updates

    cached = await updates._cached()
    latest = (cached.get("release") or {}).get("version")
    if latest and updates.newer(latest, __version__):
        return _check("updates", "Version", "ok", f"{__version__}; {latest} is available (Admin > Updates).", update_available=1)
    return _check("updates", "Version", "ok", f"{__version__}, the latest release." if latest else __version__, update_available=0)


async def collect(now: datetime | None = None) -> SystemStatus:
    now = now or datetime.now(UTC)
    checks = [
        await _database(),
        await _redis(),
        await _worker(now),
        await _queue(),
        await _events(now),
        await _integrations(now),
    ]
    checks += [c for c in (_backups(now), _disk()) if c is not None]
    checks.append(await _updates())
    overall = max((c.state for c in checks), key=lambda s: RANK[s])
    return SystemStatus(checked_at=now, overall=overall, version=__version__, checks=checks)


async def get_status(ctx: ServiceContext) -> SystemStatus:
    require_org(ctx, Permission.ORG_MANAGE)
    if get_settings().multi_tenant:
        raise NotFound("system status is for the server operator")
    return await collect()


# --------------------------------------------------------------------------- alerts


async def _alert(problems: list[Check], now: datetime) -> int:
    """Notify owners and admins of every organization, at most once per problem per six hours."""
    s = get_settings()
    window = int(now.timestamp() // ALERT_EVERY.total_seconds())
    async with system_session() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    sent = 0
    for tenant_id in tenants:
        fresh: dict[uuid.UUID, list[str]] = {}
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            admins = (
                await ctx.session.execute(
                    select(User.id, User.email).where(User.is_active.is_(True), User.org_role.in_(ORG_ADMIN_ROLES))
                )
            ).all()
            emails = {row.id: row.email for row in admins}
            for check in problems:
                event = uuid.uuid5(uuid.NAMESPACE_URL, f"glasshaus:status:{tenant_id}:{check.key}:{check.state}:{window}")
                for uid in await notify_users(
                    ctx,
                    list(emails),
                    kind=NotificationKind.SYSTEM,
                    title=f"{check.name}: {check.message}"[:200],
                    link=LINK,
                    event_id=event,
                ):
                    fresh.setdefault(uid, []).append(f"{check.name}: {check.message}")
        sent += sum(len(v) for v in fresh.values())
        if mail.available():
            link = f"{s.public_url.rstrip('/')}{LINK}"
            for uid, lines in fresh.items():
                try:
                    await mail.send(
                        mail.Mail(
                            to=emails[uid],
                            subject="Glasshaus needs attention",
                            text="\n".join(["Glasshaus found a problem:", "", *(f"- {m}" for m in lines), "", f"Details: {link}"]),
                        )
                    )
                except ServiceError as exc:
                    log.warning("status.email_failed", error=str(exc))
    return sent


async def watch(now: datetime | None = None) -> int:
    """Worker job: take a snapshot (for /metrics and the page) and alert on problems."""
    if get_settings().multi_tenant:
        return 0
    status = await collect(now)
    await get_redis().set(SNAPSHOT_KEY, status.model_dump_json(), ex=3600)
    problems = [c for c in status.checks if c.state in ("warning", "critical") and c.key not in NO_ALERT]
    return await _alert(problems, status.checked_at) if problems else 0


async def watch_worker(now: datetime | None = None) -> int:
    """API side: alert when the worker has stopped (one API process per interval, via a Redis lock)."""
    if get_settings().multi_tenant:
        return 0
    now = now or datetime.now(UTC)
    if not await get_redis().set(WATCHDOG_KEY, now.isoformat(), nx=True, ex=240):
        return 0
    check = await _worker(now)
    return await _alert([check], now) if check.state == "critical" else 0


async def watchdog_loop(interval: float = 300) -> None:  # pragma: no cover - runs for the app's lifetime
    await asyncio.sleep(120)  # let the worker start after a deploy
    while True:
        try:
            await watch_worker()
        except Exception as exc:  # noqa: BLE001 - never let the watchdog take the API down
            log.warning("status.watchdog_failed", error=str(exc))
        await asyncio.sleep(interval)


# --------------------------------------------------------------------------- Prometheus

GAUGES = {
    ("database", "size_bytes"): ("glasshaus_database_size_bytes", "Size of the database"),
    ("database", "connections"): ("glasshaus_database_connections", "Open database connections"),
    ("redis", "memory_bytes"): ("glasshaus_redis_memory_bytes", "Memory used by Redis"),
    ("worker", "heartbeat_age_seconds"): ("glasshaus_worker_heartbeat_age_seconds", "Seconds since the worker checked in"),
    ("queue", "jobs"): ("glasshaus_queue_jobs", "Background jobs waiting"),
    ("events", "unpublished"): ("glasshaus_events_unpublished", "Changes not yet delivered to live updates and integrations"),
    ("events", "oldest_seconds"): ("glasshaus_events_oldest_unpublished_seconds", "Age of the oldest undelivered change"),
    ("integrations", "failed_24h"): ("glasshaus_integration_failures_24h", "Integration messages that gave up in 24 hours"),
    ("integrations", "retrying"): ("glasshaus_integration_retrying", "Integration messages being retried"),
    ("backups", "newest_age_seconds"): ("glasshaus_backup_newest_age_seconds", "Age of the newest backup"),
    ("backups", "count"): ("glasshaus_backups", "Backups kept"),
    ("backups", "drill_ok"): ("glasshaus_backup_drill_ok", "1 if the last restore drill passed"),
    ("disk", "free_bytes"): ("glasshaus_disk_free_bytes", "Free space on the backup disk"),
    ("disk", "free_ratio"): ("glasshaus_disk_free_ratio", "Free share of the backup disk"),
    ("updates", "update_available"): ("glasshaus_update_available", "1 if a newer release is out"),
}


async def prometheus_text(now: datetime | None = None) -> str:
    """Gauges from the latest snapshot, in the Prometheus text format."""
    now = now or datetime.now(UTC)
    lines = [
        "# HELP glasshaus_build_info Running version",
        "# TYPE glasshaus_build_info gauge",
        f'glasshaus_build_info{{version="{__version__}"}} 1',
    ]
    try:
        raw = await get_redis().get(SNAPSHOT_KEY)
        snapshot = SystemStatus.model_validate(json.loads(raw)) if raw else None
    except Exception:  # noqa: BLE001 - metrics must never fail the scrape
        snapshot = None
    if snapshot is None:
        return "\n".join(lines) + "\n"
    lines += [
        "# HELP glasshaus_status_age_seconds Age of the status snapshot (the worker refreshes it every 5 minutes)",
        "# TYPE glasshaus_status_age_seconds gauge",
        f"glasshaus_status_age_seconds {(now - snapshot.checked_at).total_seconds():.0f}",
        "# HELP glasshaus_check_state Check state: 0 ok, 1 unknown, 2 warning, 3 critical",
        "# TYPE glasshaus_check_state gauge",
        *(f'glasshaus_check_state{{check="{c.key}"}} {RANK[c.state]}' for c in snapshot.checks),
    ]
    values: dict[str, Any] = {(c.key, k): v for c in snapshot.checks for k, v in c.metrics.items()}
    for key, (name, help_text) in GAUGES.items():
        if key in values:
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name} {float(values[key]):g}"]
    return "\n".join(lines) + "\n"
