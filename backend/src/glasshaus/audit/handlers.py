"""Every domain event becomes an audit entry (idempotent: the entry id is the event id)."""

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from glasshaus.audit.models import AuditEntry
from glasshaus.audit.service import redact, scrub_person
from glasshaus.core.consumers import handles


@handles("*")
async def record_event(event: dict[str, Any]) -> None:
    from glasshaus.db import system_session
    from glasshaus.models import Tenant

    actor = event.get("actor") or {}
    data = event.get("data")
    if event["aggregate_type"] == "user":
        data = scrub_person(data)  # who the person is stays out of an append-only log
    async with system_session() as session:
        if await session.get(Tenant, uuid.UUID(event["tenant_id"])) is None:
            return  # organization deleted since the event was published
        await session.execute(
            insert(AuditEntry)
            .values(
                id=uuid.UUID(event["id"]),
                tenant_id=uuid.UUID(event["tenant_id"]),
                actor_id=uuid.UUID(actor["user_id"]) if actor.get("user_id") else None,
                actor_method=actor.get("method") or "system",
                client=actor.get("client"),
                action=event["type"][:100],
                target=f"{event['aggregate_type']}:{event['aggregate_id']}"[:200],
                outcome="ok",
                detail=redact({"project_id": event.get("project_id"), "data": data}),
                # created_at is the time of recording (set by the database, keeping the chain in order).
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
