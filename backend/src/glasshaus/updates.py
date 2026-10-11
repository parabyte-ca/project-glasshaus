"""New releases: a daily check, and upgrades an owner starts from Admin > Updates.

The worker asks GitHub once a day for the latest release of this project (only the version and its
notes come back; nothing about this server is sent). Owners and admins get one notification per new
release.

The app runs in containers and can't run ``update.sh`` itself. An owner's "Upgrade" writes a request
into the upgrade folder, which is shared with the host; ``scripts/upgrade-agent.sh``, run every minute
by cron on the host, picks it up, runs ``update.sh`` (backup, pre-flight on a copy, migrate, health
check, rollback on failure) and writes its progress and log back to the same folder. Like backups, this
is server-wide, so it is only offered when the server hosts a single organization.
"""

import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import Field
from sqlalchemy import select

from glasshaus.collab.models import NotificationKind
from glasshaus.collab.service import notify_users
from glasshaus.config import get_settings
from glasshaus.core import events
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import ORG_ADMIN_ROLES, OrgRole, Permission
from glasshaus.core.schemas import Schema
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.logs import get_logger
from glasshaus.models.tenant import Tenant
from glasshaus.redis_client import get_redis
from glasshaus.version import __version__

log = get_logger(__name__)
LINK = "/admin?tab=updates"
LATEST_KEY = "glasshaus:updates:latest"
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
AGENT_STALE = timedelta(minutes=3)
MAX_NOTES = 20_000
MAX_LOG = 64 * 1024
RECHECK_AFTER = timedelta(seconds=60)


class Release(Schema):
    version: str
    name: str
    notes: str = Field(description="Release notes (Markdown).")
    url: str
    published_at: datetime | None = None


class UpgradeState(Schema):
    id: str
    state: Literal["requested", "running", "succeeded", "failed"]
    from_version: str | None = None
    to_version: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None


class Helper(Schema):
    configured: bool = Field(description="The upgrade folder is mounted into the app.")
    connected: bool = Field(description="The host helper checked in during the last few minutes.")
    last_seen: datetime | None = None


class UpdateStatus(Schema):
    current: str
    latest: Release | None
    update_available: bool
    checked_at: datetime | None
    check_error: str | None
    helper: Helper
    upgrade: UpgradeState | None
    can_upgrade: bool = Field(description="You may start an upgrade to the latest release now.")
    log: str | None = Field(None, description="The end of the last upgrade's log (owners only).")


class UpgradeRequest(Schema):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="The release to upgrade to (the latest).")


def _key(version: str) -> tuple[int, int, int]:
    m = SEMVER.match(version.strip())
    if not m:
        return (0, 0, 0)
    return (int(m[1]), int(m[2]), int(m[3]))


def newer(candidate: str, current: str) -> bool:
    return _key(candidate) > _key(current)


def _repo() -> str | None:
    """owner/name of the GitHub repository releases come from (the source URL)."""
    m = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", get_settings().source_url)
    return f"{m[1]}/{m[2]}" if m else None


def _dir() -> Path | None:
    configured = get_settings().upgrade_dir
    return Path(configured) if configured else None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > 64 * 1024:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _when(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def fetch_latest() -> Release:
    repo = _repo()
    if repo is None:
        raise InvalidInput("the source URL is not a GitHub repository, so releases can't be checked")
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"Glasshaus/{__version__}"},
        )
    if r.status_code == 404:
        raise InvalidInput("no releases published yet")
    r.raise_for_status()
    data = r.json()
    tag = str(data.get("tag_name", ""))
    if not SEMVER.match(tag):
        raise InvalidInput(f"the latest release has an unexpected tag ({tag[:40]})")
    return Release(
        version=tag.lstrip("v"),
        name=str(data.get("name") or tag)[:200],
        notes=str(data.get("body") or "")[:MAX_NOTES],
        url=str(data.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}"),
        published_at=_when(data.get("published_at")),
    )


async def _cached() -> dict[str, Any]:
    raw = await get_redis().get(LATEST_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


async def check(now: datetime | None = None) -> dict[str, Any]:
    """Ask GitHub for the latest release, remember it, and tell owners and admins once per release."""
    now = now or datetime.now(UTC)
    entry: dict[str, Any] = {"checked_at": now.isoformat()}
    try:
        release = await fetch_latest()
        entry["release"] = release.model_dump(mode="json")
    except (httpx.HTTPError, InvalidInput, ValueError) as exc:
        previous = await _cached()
        entry["release"] = previous.get("release")
        entry["error"] = str(exc)[:300] or exc.__class__.__name__
        log.warning("updates.check_failed", error=entry["error"])
        await get_redis().set(LATEST_KEY, json.dumps(entry))
        return entry
    await get_redis().set(LATEST_KEY, json.dumps(entry))
    if newer(release.version, __version__):
        await _notify(release)
    return entry


async def _notify(release: Release) -> None:
    async with system_session() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    for tenant_id in tenants:
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            admins = (
                await ctx.session.scalars(
                    select(User.id).where(User.is_active.is_(True), User.org_role.in_(ORG_ADMIN_ROLES))
                )
            ).all()
            await notify_users(
                ctx,
                list(admins),
                kind=NotificationKind.SYSTEM,
                title=f"Glasshaus {release.version} is available",
                link=LINK,
                event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"glasshaus:release:{tenant_id}:{release.version}"),
            )


async def daily_check() -> int:
    """Worker job. Single-organization servers only, and only when checking is on."""
    s = get_settings()
    if s.multi_tenant or not s.update_check:
        return 0
    entry = await check()
    return 0 if entry.get("error") else 1


def _helper(now: datetime) -> Helper:
    folder = _dir()
    if folder is None or not folder.is_dir():
        return Helper(configured=False, connected=False)
    agent = _read_json(folder / "agent.json") or {}
    seen = _when(agent.get("last_seen"))
    return Helper(configured=True, connected=bool(seen and now - seen < AGENT_STALE), last_seen=seen)


def _upgrade() -> UpgradeState | None:
    folder = _dir()
    if folder is None:
        return None
    request = _read_json(folder / "request.json")
    if request:  # waiting for the helper
        return UpgradeState(
            id=str(request.get("id", "")),
            state="requested",
            to_version=request.get("version"),
            requested_by=request.get("requested_by"),
            requested_at=_when(request.get("requested_at")),
        )
    status = _read_json(folder / "status.json")
    if not status or status.get("state") not in ("running", "succeeded", "failed"):
        return None
    return UpgradeState(
        id=str(status.get("id", ""))[:64],
        state=status["state"],
        from_version=status.get("from_version"),
        to_version=status.get("to_version"),
        requested_by=status.get("requested_by"),
        started_at=_when(status.get("started_at")),
        finished_at=_when(status.get("finished_at")),
        message=str(status.get("message") or "")[:500] or None,
    )


def _log_tail() -> str | None:
    folder = _dir()
    if folder is None:
        return None
    try:
        with (folder / "upgrade.log").open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - MAX_LOG))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def _require_single() -> None:
    if get_settings().multi_tenant:
        raise NotFound("upgrades are managed by the server operator")


async def get_status(ctx: ServiceContext, *, now: datetime | None = None) -> UpdateStatus:
    require_org(ctx, Permission.ORG_MANAGE)
    _require_single()
    now = now or datetime.now(UTC)
    cached = await _cached()
    latest = Release.model_validate(cached["release"]) if cached.get("release") else None
    available = bool(latest and newer(latest.version, __version__))
    helper = _helper(now)
    upgrade = _upgrade()
    owner = ctx.actor.org_role == OrgRole.OWNER
    busy = upgrade is not None and upgrade.state in ("requested", "running")
    return UpdateStatus(
        current=__version__,
        latest=latest,
        update_available=available,
        checked_at=_when(cached.get("checked_at")),
        check_error=cached.get("error"),
        helper=helper,
        upgrade=upgrade,
        can_upgrade=owner and available and helper.connected and not busy,
        log=_log_tail() if owner else None,
    )


async def check_now(ctx: ServiceContext) -> UpdateStatus:
    require_org(ctx, Permission.ORG_MANAGE)
    _require_single()
    cached = await _cached()
    last = _when(cached.get("checked_at"))
    if last is None or datetime.now(UTC) - last > RECHECK_AFTER:
        await check()
    return await get_status(ctx)


async def request_upgrade(ctx: ServiceContext, data: UpgradeRequest) -> UpdateStatus:
    """Owners only, from a signed-in session: write the request the host helper picks up."""
    require_org(ctx, Permission.ORG_MANAGE)
    _require_single()
    if ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can upgrade Glasshaus")
    if ctx.actor.method != "session":
        raise PermissionDenied("upgrades are started from the web app")
    current = await get_status(ctx)
    if current.upgrade is not None and current.upgrade.state in ("requested", "running"):
        raise InvalidInput("an upgrade is already under way")
    if not current.latest or data.version != current.latest.version or not current.update_available:
        raise InvalidInput("you can only upgrade to the latest release, and it must be newer than this one")
    if not current.helper.connected:
        raise InvalidInput("the upgrade helper on the server isn't running; see Admin > Updates for setup")
    folder = _dir()
    assert folder is not None
    user = await ctx.session.get(User, ctx.actor.user_id)
    request_id = uuid.uuid4()
    body = {
        "id": str(request_id),
        "version": data.version,
        "requested_by": user.email if user else None,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    tmp = folder / f".request-{request_id}.tmp"
    try:
        tmp.write_text(json.dumps(body))
        os.replace(tmp, folder / "request.json")
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise InvalidInput(
            "Glasshaus can't write to the upgrade folder; "
            "run scripts/upgrade-agent.sh --install on the server"
        ) from exc
    events.emit(
        ctx,
        "system.upgrade_requested",
        "system",
        request_id,
        {"from_version": __version__, "to_version": data.version},
    )
    return await get_status(ctx)
