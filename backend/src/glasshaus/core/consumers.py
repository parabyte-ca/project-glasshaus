"""Domain-event consumers: handlers subscribe to event types and run in the worker.

Delivery is at-least-once via a Redis Streams consumer group; handlers must be idempotent.
Failed entries are retried after ``RETRY_IDLE_MS`` and dead-lettered after ``MAX_DELIVERIES``.
"""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import orjson
from redis.exceptions import ResponseError

from glasshaus.core.events import STREAM
from glasshaus.logs import get_logger

Event = dict[str, Any]
Handler = Callable[[Event], Awaitable[None]]

GROUP = "glasshaus-workers"
DEAD_LETTER = "glasshaus:events:dead"
RETRY_IDLE_MS = 60_000
MAX_DELIVERIES = 5
log = get_logger(__name__)
_handlers: dict[str, list[Handler]] = defaultdict(list)


def handles(*event_types: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        for t in event_types:
            if fn not in _handlers[t]:
                _handlers[t].append(fn)
        return fn

    return register


def load_handlers() -> None:
    """Import every module that registers handlers."""
    import glasshaus.collab.handlers  # noqa: F401


async def dispatch(event: Event) -> None:
    for handler in _handlers.get(event["type"], []):
        await handler(event)


async def _ensure_group() -> None:
    from glasshaus.redis_client import get_redis

    try:
        await get_redis().xgroup_create(STREAM, GROUP, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _process(entry_id: str, fields: dict[str, str], deliveries: int = 1) -> None:
    from glasshaus.redis_client import get_redis

    redis = get_redis()
    try:
        await dispatch(orjson.loads(fields["event"]))
    except Exception:
        log.warning("consumer.handler_failed", entry=entry_id, deliveries=deliveries, exc_info=True)
        if deliveries < MAX_DELIVERIES:
            return
        await redis.xadd(
            DEAD_LETTER, {"event": fields["event"], "entry": entry_id}, maxlen=10_000, approximate=True
        )
        log.error("consumer.dead_lettered", entry=entry_id)
    await redis.xack(STREAM, GROUP, entry_id)


async def consume(stop: asyncio.Event, consumer: str | None = None, *, block_ms: int = 5000) -> None:
    from glasshaus.redis_client import get_redis

    load_handlers()
    await _ensure_group()
    redis = get_redis()
    name = consumer or f"worker-{uuid.uuid4().hex[:8]}"
    log.info("consumer.started", consumer=name)
    while not stop.is_set():
        try:
            # Retry entries another (or this) consumer failed on and left idle.
            _, claimed, _ = await redis.xautoclaim(STREAM, GROUP, name, min_idle_time=RETRY_IDLE_MS, count=50)
            for entry_id, fields in claimed:
                info = await redis.xpending_range(STREAM, GROUP, min=entry_id, max=entry_id, count=1)
                await _process(entry_id, fields, info[0]["times_delivered"] if info else MAX_DELIVERIES)
            batches = await redis.xreadgroup(GROUP, name, {STREAM: ">"}, count=50, block=block_ms)
            for _, entries in batches or []:
                for entry_id, fields in entries:
                    await _process(entry_id, fields)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("consumer.loop_error", exc_info=True)
            await asyncio.sleep(2)
    log.info("consumer.stopped", consumer=name)
