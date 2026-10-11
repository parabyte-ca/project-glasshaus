"""Domain events: written to the outbox inside the business transaction, then relayed to Redis.

Consumers (automations, webhooks, notifications, realtime, audit) read the Redis stream
``glasshaus:events``; browsers get live updates via the per-tenant pub/sub channel.
The worker sweeps any events whose post-commit relay failed.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import orjson
from pydantic import BaseModel
from sqlalchemy import select, update

from glasshaus.core.context import ServiceContext
from glasshaus.core.models import DomainEventRecord
from glasshaus.logs import get_logger

STREAM = "glasshaus:events"
STREAM_MAXLEN = 100_000
log = get_logger(__name__)


def channel_for(tenant_id: uuid.UUID) -> str:
    return f"glasshaus:events:{tenant_id}"


def emit(
    ctx: ServiceContext,
    type_: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: BaseModel | dict[str, Any],
    *,
    project_id: uuid.UUID | None = None,
) -> None:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    if project_id is None and aggregate_type == "project":
        project_id = aggregate_id
    record = DomainEventRecord(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        type=type_,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        project_id=project_id,
        actor_id=ctx.actor.user_id,
        actor_method=ctx.actor.method,
        actor_client=ctx.actor.client,
        payload=orjson.loads(orjson.dumps(data, default=str)),
    )
    ctx.session.add(record)
    ctx.pending_events.append(record.id)


def envelope(record: DomainEventRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "type": record.type,
        "tenant_id": str(record.tenant_id),
        "aggregate_type": record.aggregate_type,
        "aggregate_id": str(record.aggregate_id),
        "project_id": str(record.project_id) if record.project_id else None,
        "actor": {
            "user_id": str(record.actor_id) if record.actor_id else None,
            "method": record.actor_method,
            "client": record.actor_client,
        },
        "occurred_at": record.occurred_at.isoformat(),
        "data": record.payload,
    }


async def relay_events(event_ids: list[uuid.UUID] | None = None, *, limit: int = 500) -> int:
    """Publish unpublished events (optionally only ``event_ids``) and mark them published."""
    from glasshaus.db import system_session
    from glasshaus.redis_client import get_redis

    try:
        async with system_session() as session:
            stmt = (
                select(DomainEventRecord)
                .where(DomainEventRecord.published_at.is_(None))
                .order_by(DomainEventRecord.occurred_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            if event_ids is not None:
                stmt = stmt.where(DomainEventRecord.id.in_(event_ids))
            records = list((await session.scalars(stmt)).all())
            if not records:
                return 0
            redis = get_redis()
            async with redis.pipeline(transaction=False) as pipe:
                for record in records:
                    full = envelope(record)
                    pipe.xadd(
                        STREAM, {"event": orjson.dumps(full).decode()}, maxlen=STREAM_MAXLEN, approximate=True
                    )
                    # Live updates only need identifiers (clients refetch through the API), so every
                    # connected tab parses a few hundred bytes, not the whole task.
                    slim = {k: v for k, v in full.items() if k not in ("data", "tenant_id", "occurred_at")}
                    slim["actor"] = {"user_id": full["actor"]["user_id"]}
                    pipe.publish(channel_for(record.tenant_id), orjson.dumps(slim).decode())
                await pipe.execute()
            await session.execute(
                update(DomainEventRecord)
                .where(DomainEventRecord.id.in_([r.id for r in records]))
                .values(published_at=datetime.now(UTC))
            )
            return len(records)
    except Exception:
        log.warning("events.relay_failed", exc_info=True)
        return 0
