"""Personal data: export everything held about one person, and erase a person (anonymise).

Erasing keeps the organization's work intact (tasks, time, history) but removes who the person was:
their name and email become "Former user", their sign-ins, tokens, devices, links to identity providers
and personal notifications are deleted, and the text of their comments is removed. Audit entries are
kept for the audit retention period (they are the record of what happened) and name the person only by
an id that now resolves to "Former user".
"""

import io
import uuid
import zipfile
from datetime import UTC, date, datetime
from typing import Any

import orjson
from pydantic import Field
from sqlalchemy import delete, or_, select, update

from glasshaus.core import events
from glasshaus.core.authz import require_org
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.core.schemas import Schema
from glasshaus.identity.models import ApiToken, AuthSession, User, is_assistant

ERASED_DOMAIN = "erased.invalid"
REMOVED = "[removed]"
# Never in a personal export: credentials, secret hashes and device keys.
SECRET_COLUMNS = {
    "password_hash",
    "token_hash",
    "refresh_hash",
    "webhook_secret",
    "secret",
    "client_secret",
    "p256dh",
    "auth",
    "code_challenge",
}
SKIP_TABLES = {"oauth_requests", "audit_log", "domain_events"}  # the last two are added by actor below


class EraseRequest(Schema):
    confirm_email: str = Field(description="The person's current email address, to confirm.")


class EraseResult(Schema):
    user_id: uuid.UUID
    name: str
    removed: dict[str, int]


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date | uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


async def _person(ctx: ServiceContext, user_id: uuid.UUID) -> User:
    user = await ctx.session.get(User, user_id)
    if user is None or is_assistant(user):
        raise NotFound("user not found")
    return user


async def export_person(ctx: ServiceContext, user_id: uuid.UUID) -> bytes:
    """A zip of every row that refers to this person (one JSON Lines file per table), secrets left out.

    People export their own data; organization admins can export anyone's (a subject access request).
    """
    from glasshaus.audit.models import AuditEntry
    from glasshaus.core.authz import visible_projects_clause
    from glasshaus.core.models import DomainEventRecord
    from glasshaus.models import Base
    from glasshaus.projects.models import Project

    if ctx.actor.method != "session":
        raise PermissionDenied("exports require an interactive session")
    own = user_id == ctx.actor.user_id
    if not own:
        require_org(ctx, Permission.USER_MANAGE)
    user = await _person(ctx, user_id)
    counts: dict[str, int] = {}
    buffer = io.BytesIO()

    def write(archive: zipfile.ZipFile, name: str, rows: list[dict[str, Any]]) -> None:
        counts[name] = len(rows)
        lines = [orjson.dumps({k: _jsonable(v) for k, v in r.items()}, default=str) for r in rows]
        archive.writestr(f"{name}.jsonl", b"\n".join(lines) + (b"\n" if lines else b""))

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table in Base.metadata.sorted_tables:
            if table.name in SKIP_TABLES or "tenant_id" not in table.c:
                continue
            if table.name == "users":
                refs = [table.c.id, *(c for c in table.c if c.name == "manager_id")]
                where = table.c.id == user.id
            else:
                refs = [c for c in table.c if any(fk.column.table.name == "users" for fk in c.foreign_keys)]
                if not refs:
                    continue
                where = or_(*(c == user.id for c in refs))
            columns = [c for c in table.c if c.name not in SECRET_COLUMNS]
            stmt = select(*columns).where(table.c.tenant_id == ctx.tenant_id, where)
            if own and "project_id" in table.c:
                # Someone removed from a project doesn't get its content back through their export.
                stmt = stmt.where(
                    or_(
                        table.c.project_id.is_(None),
                        table.c.project_id.in_(select(Project.id).where(visible_projects_clause(ctx))),
                    )
                )
            result = await ctx.session.execute(stmt)
            rows = [dict(r._mapping) for r in result]
            if rows:
                write(archive, str(table.name), rows)
        audit_rows = (
            await ctx.session.execute(
                select(
                    AuditEntry.created_at,
                    AuditEntry.action,
                    AuditEntry.outcome,
                    AuditEntry.client,
                    AuditEntry.target,
                    AuditEntry.detail,
                )
                .where(AuditEntry.actor_id == user.id)
                .order_by(AuditEntry.seq)
            )
        ).all()
        write(archive, "audit_log", [dict(r._mapping) for r in audit_rows])
        event_rows = (
            await ctx.session.execute(
                select(
                    DomainEventRecord.occurred_at,
                    DomainEventRecord.type,
                    DomainEventRecord.aggregate_type,
                    DomainEventRecord.aggregate_id,
                    DomainEventRecord.payload,
                )
                .where(DomainEventRecord.actor_id == user.id)
                .order_by(DomainEventRecord.occurred_at)
            )
        ).all()
        write(archive, "activity", [dict(r._mapping) for r in event_rows])
        manifest = {
            "person": {"id": str(user.id), "name": user.name, "email": user.email},
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": str(ctx.actor.user_id),
            "files": counts,
            "excluded_columns": sorted(SECRET_COLUMNS),
            "note": "Rows that refer to this person: their profile, work assigned to or created by them, "
            "comments, time, sessions, tokens (without secrets), notifications, settings, audit entries "
            "and activity they caused.",
        }
        archive.writestr("manifest.json", orjson.dumps(manifest, option=orjson.OPT_INDENT_2))
    events.emit(ctx, "user.exported", "user", user.id, {"user_id": str(user.id), "files": counts})
    return buffer.getvalue()


async def erase_person(ctx: ServiceContext, user_id: uuid.UUID, data: EraseRequest) -> EraseResult:
    """Anonymise a person: keep their work, remove who they were. Cannot be undone."""
    from glasshaus.collab.models import Comment, Notification
    from glasshaus.core.models import DomainEventRecord
    from glasshaus.integrations.models import CalendarFeed
    from glasshaus.oauth.models import OAuthGrant
    from glasshaus.push import PushSubscription
    from glasshaus.reports.models import ReportAlert, ReportSubscription
    from glasshaus.sso.models import UserIdentity
    from glasshaus.timetracking.models import RunningTimer

    require_org(ctx, Permission.USER_MANAGE)
    if ctx.actor.method != "session":
        raise PermissionDenied("erasing a person requires an interactive session")
    user = await _person(ctx, user_id)
    if user.id == ctx.actor.user_id:
        raise InvalidInput("you cannot erase yourself; ask another admin")
    if user.org_role == OrgRole.OWNER and ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can erase an owner")
    if user.erased_at is not None:
        raise InvalidInput("this person was already erased")
    if data.confirm_email.strip().lower() != user.email.lower():
        raise InvalidInput("type the person's email address to confirm")

    s = ctx.session
    removed: dict[str, int] = {}

    async def drop(name: str, stmt: Any) -> None:
        removed[name] = int((await s.execute(stmt)).rowcount or 0)  # type: ignore[attr-defined]

    await drop("sessions", delete(AuthSession).where(AuthSession.user_id == user.id))
    await drop("api_tokens", delete(ApiToken).where(ApiToken.user_id == user.id))
    await drop("app_connections", delete(OAuthGrant).where(OAuthGrant.user_id == user.id))
    await drop("devices", delete(PushSubscription).where(PushSubscription.user_id == user.id))
    await drop("sign_in_links", delete(UserIdentity).where(UserIdentity.user_id == user.id))
    await drop("calendar_feeds", delete(CalendarFeed).where(CalendarFeed.user_id == user.id))
    await drop("notifications", delete(Notification).where(Notification.user_id == user.id))
    await drop("report_emails", delete(ReportSubscription).where(ReportSubscription.user_id == user.id))
    await drop("report_alerts", delete(ReportAlert).where(ReportAlert.user_id == user.id))
    await drop("timers", delete(RunningTimer).where(RunningTimer.user_id == user.id))
    await drop(
        "comments",
        update(Comment)
        .where(Comment.author_id == user.id, Comment.body != REMOVED)
        .values(body=REMOVED, mentions=[]),
    )
    # Events about the account itself carried its name and email; keep that they happened, not the details.
    await drop(
        "account_events",
        update(DomainEventRecord)
        .where(DomainEventRecord.aggregate_type == "user", DomainEventRecord.aggregate_id == user.id)
        .values(payload={"erased": True}),
    )
    await s.execute(
        update(User).where(User.manager_id == user.id).values(manager_id=None, manager_source=None)
    )
    label = f"Former user {user.id.hex[:6]}"
    user.name = label
    user.email = f"erased-{user.id.hex}@{ERASED_DOMAIN}"
    user.password_hash = None
    user.is_active = False
    user.external_id = None
    user.job_title = None
    user.department = None
    user.manager_id = None
    user.manager_source = None
    user.last_login_at = None
    user.onboarding = {}
    user.erased_at = datetime.now(UTC)
    await s.flush()
    events.emit(ctx, "user.erased", "user", user.id, {"user_id": str(user.id), "removed": removed})
    return EraseResult(user_id=user.id, name=label, removed=removed)
