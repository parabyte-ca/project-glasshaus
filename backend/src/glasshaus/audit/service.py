"""Audit trail. Writes use their own transaction so a failed action is still recorded."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from glasshaus.audit.models import AuditEntry
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.rbac import Permission
from glasshaus.core.schemas import Schema

MAX_DETAIL_CHARS = 2000
SECRET_KEYS = {"password", "token", "secret", "client_secret", "authorization"}


class AuditRead(Schema):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_method: str
    client: str | None
    action: str
    target: str | None
    outcome: str
    detail: dict[str, Any]
    duration_ms: int | None
    created_at: datetime


def redact(value: Any, depth: int = 0) -> Any:
    """Drop secrets and cap sizes so arguments are safe and cheap to store."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in SECRET_KEYS else redact(v, depth + 1))
            for k, v in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


async def record(
    actor: Actor,
    action: str,
    *,
    outcome: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    await record_raw(
        actor.tenant_id,
        action,
        outcome=outcome,
        actor_id=actor.user_id,
        method=actor.method,
        client=actor.client,
        target=target,
        detail=detail,
        duration_ms=duration_ms,
    )


async def record_raw(
    tenant_id: uuid.UUID,
    action: str,
    *,
    outcome: str,
    actor_id: uuid.UUID | None = None,
    method: str = "system",
    client: str | None = None,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    """Write one entry in its own transaction, so it survives the caller's rollback (failed logins)."""
    from glasshaus.db import unit_of_work

    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        ctx.session.add(
            AuditEntry(
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_method=method[:20],
                client=client[:200] if client else None,
                action=action[:100],
                target=target[:200] if target else None,
                outcome=outcome,
                detail=redact(detail or {}),
                duration_ms=duration_ms,
            )
        )


async def list_entries(
    ctx: ServiceContext,
    *,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    outcome: str | None = None,
    before: datetime | None = None,
    limit: int = 100,
) -> list[AuditRead]:
    """Newest first. Page with ``before`` = the last entry's ``created_at``."""
    require_org(ctx, Permission.ORG_MANAGE)
    stmt = select(AuditEntry).order_by(AuditEntry.created_at.desc()).limit(min(max(limit, 1), 500))
    if action:
        stmt = stmt.where(AuditEntry.action.startswith(action))
    if actor_id:
        stmt = stmt.where(AuditEntry.actor_id == actor_id)
    if outcome:
        stmt = stmt.where(AuditEntry.outcome == outcome)
    if before:
        stmt = stmt.where(AuditEntry.created_at < before)
    return [AuditRead.model_validate(e) for e in (await ctx.session.scalars(stmt)).all()]
