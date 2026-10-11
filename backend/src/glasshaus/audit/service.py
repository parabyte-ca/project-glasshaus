"""Audit trail. Writes use their own transaction so a failed action is still recorded."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from glasshaus.audit.models import AuditEntry
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.rbac import Permission
from glasshaus.core.schemas import Schema

MAX_DETAIL_CHARS = 2000
SECRET_KEYS = {"password", "token", "secret", "client_secret", "authorization"}


class AuditRead(Schema):
    id: uuid.UUID
    seq: int
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


class ChainProblem(Schema):
    seq: int
    id: uuid.UUID
    created_at: datetime
    problem: str


class ChainCheck(Schema):
    ok: bool
    entries: int
    first_seq: int | None
    last_seq: int | None
    head: str | None = (
        None  # hex hash of the newest entry: note it down to prove later entries weren't rewritten
    )
    starts_after_purge: bool = False
    problems: list[ChainProblem]


VERIFY_SQL = text(
    """
    SELECT seq, id, created_at, action,
           hash = glasshaus_audit_hash(prev_hash, a) AS hash_ok,
           lag(seq) OVER w AS prev_seq,
           prev_hash IS NOT DISTINCT FROM lag(hash) OVER w AS link_ok,
           encode(hash, 'hex') AS hex
    FROM audit_log a WHERE tenant_id = :t WINDOW w AS (ORDER BY seq) ORDER BY seq
    """
)


async def verify(ctx: ServiceContext) -> ChainCheck:
    """Recompute this organization's hash chain: any edited, removed or inserted entry shows up."""
    require_org(ctx, Permission.ORG_MANAGE)
    rows = (await ctx.session.execute(VERIFY_SQL, {"t": ctx.tenant_id})).all()
    problems: list[ChainProblem] = []
    for r in rows:
        problem = None
        if not r.hash_ok:
            problem = "changed after it was recorded"
        elif r.prev_seq is not None and r.seq != r.prev_seq + 1:
            problem = f"entries {r.prev_seq + 1} to {r.seq - 1} are missing"
        elif r.prev_seq is not None and not r.link_ok:
            problem = "does not follow the entry before it"
        if problem:
            problems.append(ChainProblem(seq=r.seq, id=r.id, created_at=r.created_at, problem=problem))
    first = rows[0] if rows else None
    check = ChainCheck(
        ok=not problems,
        entries=len(rows),
        first_seq=first.seq if first else None,
        last_seq=rows[-1].seq if rows else None,
        head=rows[-1].hex if rows else None,
        starts_after_purge=bool(first and first.seq != 1),
        problems=problems[:50],
    )
    await record(
        ctx.actor,
        "audit.verified",
        outcome="ok" if check.ok else "error",
        detail={"entries": check.entries, "problems": len(problems), "head": check.head},
    )
    return check
