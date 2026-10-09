"""Organization governance: settings and retention, data export, and admin actions on accounts."""

import io
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import orjson
from pydantic import Field, field_validator
from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert

from glasshaus.core import events
from glasshaus.core.authz import require_org
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.core.schemas import Schema
from glasshaus.governance.models import OrgSettings
from glasshaus.identity import security
from glasshaus.identity.models import ApiToken, AuthSession, User, is_assistant

AiFeature = Literal["summaries", "drafting", "risks", "search", "reports", "assistant"]
TrustedKind = Literal["comment"]

# Columns never exported (credentials and secret hashes).
EXPORT_EXCLUDED_COLUMNS = {
    "password_hash",
    "token_hash",
    "refresh_hash",
    "webhook_secret",
    "secret",
    "client_secret",
}
# Tables never exported (session state and machine credentials).
EXPORT_EXCLUDED_TABLES = {"auth_sessions", "oauth_grants", "oauth_requests", "oauth_clients", "scim_tokens"}


class OrgSettingsRead(Schema):
    audit_retention_days: int = Field(description="Days to keep audit entries (0 = forever).")
    activity_retention_days: int = Field(description="Days to keep the activity/event history (0 = forever).")
    notification_retention_days: int = Field(description="Days to keep read and unread notifications.")
    deleted_task_retention_days: int = Field(
        description="Days a deleted task stays restorable before it is purged (0 = forever). Tasks with "
        "logged time are kept."
    )
    ai_enabled: bool = Field(
        description="AI assistant on for this organization (also needs a provider configured on the server)."
    )
    ai_features: list[AiFeature] = Field(description="AI features people may use when the assistant is on.")
    assistant_trusted: list[TrustedKind] = Field(
        description="Project-assistant suggestions projects may let it apply without approval (a ceiling)."
    )


class OrgSettingsUpdate(Schema):
    audit_retention_days: int | None = Field(None, ge=0, le=3650)
    activity_retention_days: int | None = Field(None, ge=0, le=3650)
    notification_retention_days: int | None = Field(None, ge=0, le=3650)
    deleted_task_retention_days: int | None = Field(None, ge=0, le=3650)
    ai_enabled: bool | None = None
    ai_features: list[AiFeature] | None = None
    assistant_trusted: list[TrustedKind] | None = None

    @field_validator("ai_features", "assistant_trusted")
    @classmethod
    def _unique(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else sorted(set(v))


class PasswordReset(Schema):
    new_password: str = Field(min_length=12, max_length=1024)

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        from glasshaus.identity.passwords import password_problem

        if problem := password_problem(v):
            raise ValueError(problem)
        return v


class RetentionResult(Schema):
    audit: int
    activity: int
    notifications: int
    tasks: int


async def _settings_row(ctx: ServiceContext) -> OrgSettings:
    row = await ctx.session.get(OrgSettings, ctx.tenant_id)
    if row is None:
        await ctx.session.execute(
            insert(OrgSettings).values(tenant_id=ctx.tenant_id).on_conflict_do_nothing()
        )
        row = await ctx.session.get(OrgSettings, ctx.tenant_id)
    assert row is not None
    return row


async def get_settings(ctx: ServiceContext) -> OrgSettingsRead:
    require_org(ctx, Permission.ORG_MANAGE)
    return OrgSettingsRead.model_validate(await _settings_row(ctx))


async def update_settings(ctx: ServiceContext, data: OrgSettingsUpdate) -> OrgSettingsRead:
    require_org(ctx, Permission.ORG_MANAGE)
    row = await _settings_row(ctx)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(row, field, value)
    await ctx.session.flush()
    result = OrgSettingsRead.model_validate(row)
    events.emit(ctx, "org.settings_updated", "tenant", ctx.tenant_id, {"changes": changes})
    return result


# --------------------------------------------------------------------------- accounts


async def revoke_user_sessions(ctx: ServiceContext, user_id: uuid.UUID, *, tokens: bool = False) -> None:
    """End browser sessions (and optionally API tokens and OAuth grants) for a user."""
    from glasshaus.oauth.models import OAuthGrant

    now = datetime.now(UTC)
    await ctx.session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if tokens:
        await ctx.session.execute(
            update(ApiToken)
            .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await ctx.session.execute(
            update(OAuthGrant)
            .where(OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None))
            .values(revoked_at=now)
        )


async def reset_password(ctx: ServiceContext, user_id: uuid.UUID, data: PasswordReset) -> None:
    """Set a new password for someone else (admins); ends their sessions."""
    require_org(ctx, Permission.USER_MANAGE)
    if ctx.actor.method != "session":
        raise PermissionDenied("password resets require an interactive session")
    user = await ctx.session.get(User, user_id)
    if user is None or is_assistant(user):
        raise NotFound("user not found")
    if user.org_role == OrgRole.OWNER and ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can reset an owner's password")
    if user.id == ctx.actor.user_id:
        raise InvalidInput("use Account > Change password for your own password")
    user.password_hash = security.hash_password(data.new_password)
    await revoke_user_sessions(ctx, user.id)
    events.emit(ctx, "user.password_reset", "user", user.id, {"user_id": str(user.id)})


async def sign_out_everywhere(ctx: ServiceContext, user_id: uuid.UUID) -> None:
    """Admin action: end every session, API token and OAuth grant of a user."""
    require_org(ctx, Permission.USER_MANAGE)
    user = await ctx.session.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    if user.org_role == OrgRole.OWNER and ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can sign out an owner")
    await revoke_user_sessions(ctx, user.id, tokens=True)
    events.emit(ctx, "user.signed_out", "user", user.id, {"user_id": str(user.id)})


# --------------------------------------------------------------------------- retention


async def apply_retention(now: datetime | None = None) -> RetentionResult:
    """Delete data older than each organization's retention settings (worker cron, daily)."""
    from glasshaus.audit.models import AuditEntry
    from glasshaus.collab.models import Notification
    from glasshaus.core.models import DomainEventRecord
    from glasshaus.db import system_session
    from glasshaus.models import Tenant
    from glasshaus.tasks.models import Task
    from glasshaus.timetracking.models import TimeEntry

    now = now or datetime.now(UTC)
    totals = {"audit": 0, "activity": 0, "notifications": 0, "tasks": 0}
    async with system_session() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
        rows = {r.tenant_id: r for r in (await session.scalars(select(OrgSettings))).all()}
        for tenant_id in tenants:
            cfg = rows.get(tenant_id) or OrgSettings(
                tenant_id=tenant_id,
                audit_retention_days=365,
                activity_retention_days=0,
                notification_retention_days=90,
                deleted_task_retention_days=30,
            )
            plans: list[tuple[str, int, Any]] = [
                (
                    "audit",
                    cfg.audit_retention_days,
                    lambda c, t=tenant_id: delete(AuditEntry).where(
                        AuditEntry.tenant_id == t, AuditEntry.created_at < c
                    ),
                ),
                (
                    "activity",
                    cfg.activity_retention_days,
                    lambda c, t=tenant_id: delete(DomainEventRecord).where(
                        DomainEventRecord.tenant_id == t,
                        DomainEventRecord.occurred_at < c,
                        DomainEventRecord.published_at.is_not(None),
                    ),
                ),
                (
                    "notifications",
                    cfg.notification_retention_days,
                    lambda c, t=tenant_id: delete(Notification).where(
                        Notification.tenant_id == t, Notification.created_at < c
                    ),
                ),
                (
                    "tasks",
                    cfg.deleted_task_retention_days,
                    lambda c, t=tenant_id: delete(Task).where(
                        Task.tenant_id == t,
                        Task.deleted_at.is_not(None),
                        Task.deleted_at < c,
                        ~exists().where(TimeEntry.task_id == Task.id),
                    ),
                ),
            ]
            for key, days, stmt in plans:
                if days > 0:
                    result = await session.execute(stmt(now - timedelta(days=days)))
                    totals[key] += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return RetentionResult(**totals)


# --------------------------------------------------------------------------- export


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date | uuid.UUID):
        return str(value)
    return value


async def export_organization(ctx: ServiceContext) -> bytes:
    """A zip with one JSON Lines file per table (this organization's rows only, secrets excluded)."""
    from glasshaus.models import Base, Tenant

    require_org(ctx, Permission.ORG_MANAGE)
    if ctx.actor.method != "session":
        raise PermissionDenied("exports require an interactive session")
    buffer = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        tenant = await ctx.session.get(Tenant, ctx.tenant_id)
        assert tenant is not None
        for table in Base.metadata.sorted_tables:
            if table.name in EXPORT_EXCLUDED_TABLES or "tenant_id" not in table.c:
                continue
            columns = [c for c in table.c if c.name not in EXPORT_EXCLUDED_COLUMNS]
            result = await ctx.session.execute(select(*columns).where(table.c.tenant_id == ctx.tenant_id))
            lines = [
                orjson.dumps({str(k): _jsonable(v) for k, v in row._mapping.items()}, default=str)
                for row in result
            ]
            counts[str(table.name)] = len(lines)
            archive.writestr(f"{table.name}.jsonl", b"\n".join(lines) + (b"\n" if lines else b""))
        manifest = {
            "organization": {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name},
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": str(ctx.actor.user_id),
            "tables": counts,
            "excluded_columns": sorted(EXPORT_EXCLUDED_COLUMNS),
        }
        archive.writestr("manifest.json", orjson.dumps(manifest, option=orjson.OPT_INDENT_2))
    events.emit(ctx, "org.exported", "tenant", ctx.tenant_id, {"tables": counts})
    return buffer.getvalue()
