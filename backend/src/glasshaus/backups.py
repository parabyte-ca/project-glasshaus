"""Backup health, read from the backup folder (mounted read-only into the app containers).

The `backup` service writes dumps and, every few days, a restore drill result (drill-status.json).
Owners and admins see both in Admin > Backups, and get a notification (and an email, if the server
has email) once a day while something is wrong: no recent backup, or a failed or overdue drill.
Backups are server-wide, so this is only shown when the server hosts a single organization.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import Field
from sqlalchemy import select

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

log = get_logger(__name__)
LINK = "/admin?tab=backups"


class BackupFile(Schema):
    name: str
    bytes: int
    created_at: datetime


class DrillResult(Schema):
    finished_at: datetime
    ok: bool
    dump: str
    dump_bytes: int = 0
    seconds: int = 0
    tables: int = 0
    revision: str = ""
    live_revision: str = ""
    rows: dict[str, int] = Field(default_factory=dict)
    error: str = ""


class Problem(Schema):
    code: str
    message: str


class BackupStatus(Schema):
    available: bool = Field(description="False when the backup folder is not visible to the app.")
    folder: str
    interval_hours: int
    drill_days: int
    count: int
    total_bytes: int
    latest: list[BackupFile] = Field(description="Newest first, up to 10.")
    drill: DrillResult | None
    problems: list[Problem]


def status(now: datetime | None = None) -> BackupStatus:
    s = get_settings()
    now = now or datetime.now(UTC)
    folder = Path(s.backup_status_dir) if s.backup_status_dir else None
    if folder is None or not folder.is_dir():
        return BackupStatus(
            available=False,
            folder=s.backup_status_dir,
            interval_hours=s.backup_interval_hours,
            drill_days=s.backup_drill_days,
            count=0,
            total_bytes=0,
            latest=[],
            drill=None,
            problems=[],
        )
    if not os.access(folder, os.R_OK | os.X_OK):
        return BackupStatus(
            available=True,
            folder=s.backup_status_dir,
            interval_hours=s.backup_interval_hours,
            drill_days=s.backup_drill_days,
            count=0,
            total_bytes=0,
            latest=[],
            drill=None,
            problems=[
                Problem(
                    code="folder_unreadable",
                    message="Glasshaus cannot read the backup folder; check its permissions.",
                )
            ],
        )
    files = []
    for path in folder.glob("glasshaus-*.dump"):
        try:
            st = path.stat()
        except OSError:
            continue
        files.append(
            BackupFile(name=path.name, bytes=st.st_size, created_at=datetime.fromtimestamp(st.st_mtime, UTC))
        )
    files.sort(key=lambda f: f.created_at, reverse=True)
    drill: DrillResult | None = None
    problems: list[Problem] = []
    drill_file = folder / "drill-status.json"
    if drill_file.is_file():
        try:
            drill = DrillResult.model_validate(json.loads(drill_file.read_text()))
        except (OSError, ValueError):
            problems.append(
                Problem(code="drill_unreadable", message="The last restore drill result could not be read.")
            )

    stale_after = timedelta(hours=s.backup_interval_hours * 2 + 1)
    if not files:
        problems.append(Problem(code="no_backup", message="There are no backups yet."))
    elif now - files[0].created_at > stale_after:
        hours = int((now - files[0].created_at).total_seconds() // 3600)
        problems.append(
            Problem(
                code="backup_stale",
                message=(
                    f"The newest backup is {hours} hours old; "
                    f"backups should run every {s.backup_interval_hours} hours."
                ),
            )
        )
    if s.backup_drill_days > 0 and files:
        if drill is not None and not drill.ok:
            problems.append(
                Problem(
                    code="drill_failed",
                    message=f"The last restore drill failed: {drill.error or 'unknown error'}",
                )
            )
        elif drill is None and now - files[-1].created_at > timedelta(days=s.backup_drill_days * 2):
            problems.append(Problem(code="drill_missing", message="No restore drill has run yet."))
        elif drill is not None and now - drill.finished_at > timedelta(days=s.backup_drill_days * 2):
            problems.append(
                Problem(
                    code="drill_overdue",
                    message=f"The last restore drill was {(now - drill.finished_at).days} days ago.",
                )
            )
    return BackupStatus(
        available=True,
        folder=s.backup_status_dir,
        interval_hours=s.backup_interval_hours,
        drill_days=s.backup_drill_days,
        count=len(files),
        total_bytes=sum(f.bytes for f in files),
        latest=files[:10],
        drill=drill,
        problems=problems,
    )


async def get_status(ctx: ServiceContext) -> BackupStatus:
    require_org(ctx, Permission.ORG_MANAGE)
    if get_settings().multi_tenant:
        raise NotFound("backups are managed by the server operator")
    return status()


async def watch(now: datetime | None = None) -> int:
    """Worker job: tell owners and admins about backup problems, at most once a day per problem."""
    s = get_settings()
    if s.multi_tenant or not s.backup_status_dir:
        return 0
    now = now or datetime.now(UTC)
    found = status(now)
    if not found.available or not found.problems:
        return 0
    async with system_session() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    sent = 0
    for tenant_id in tenants:
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            admins = (
                await ctx.session.execute(
                    select(User.id, User.email).where(
                        User.is_active.is_(True), User.org_role.in_(ORG_ADMIN_ROLES)
                    )
                )
            ).all()
            emails = {row.id: row.email for row in admins}
            fresh: dict[uuid.UUID, list[str]] = {}
            for problem in found.problems:
                event = uuid.uuid5(
                    uuid.NAMESPACE_URL, f"glasshaus:backup:{tenant_id}:{problem.code}:{now:%Y-%m-%d}"
                )
                for uid in await notify_users(
                    ctx,
                    list(emails),
                    kind=NotificationKind.SYSTEM,
                    title=f"Backups: {problem.message}",
                    link=LINK,
                    event_id=event,
                ):
                    fresh.setdefault(uid, []).append(problem.message)
        sent += sum(len(v) for v in fresh.values())
        if mail.available():
            link = f"{s.public_url.rstrip('/')}{LINK}"
            for uid, messages in fresh.items():
                try:
                    await mail.send(
                        mail.Mail(
                            to=emails[uid],
                            subject="Glasshaus backups need attention",
                            text="\n".join(
                                [
                                    "Glasshaus found a problem with its backups:",
                                    "",
                                    *(f"- {m}" for m in messages),
                                    "",
                                    f"Details: {link}",
                                ]
                            ),
                        )
                    )
                except ServiceError as exc:
                    log.warning("backup_watch.email_failed", error=str(exc))
    return sent
