"""Domain-event consumers: handlers subscribe to event types and run in the worker.

Delivery is at-least-once via a Redis Streams consumer group; handlers must be idempotent.
Failed entries are retried after ``RETRY_IDLE_MS`` and dead-lettered after ``MAX_DELIVERIES``.
Events for different aggregates run concurrently (up to ``CONCURRENCY``); events for the same
aggregate (a task and its comments, say) run one after another in stream order.
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
CONCURRENCY = 8
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
    """Import every module that registers handlers, and every ORM model so foreign keys resolve
    (the worker never imports the web app, which otherwise pulls the models in)."""
    import glasshaus.audit.handlers
    import glasshaus.automation.handlers
    import glasshaus.collab.handlers
    import glasshaus.integrations.handlers
    import glasshaus.models  # noqa: F401


async def dispatch(event: Event) -> None:
    """Run the handlers for the event's type, then catch-all ("*") handlers such as the audit log."""
    for handler in [*_handlers.get(event["type"], []), *_handlers.get("*", [])]:
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


def _ordering_key(fields: dict[str, str]) -> str:
    try:
        event = orjson.loads(fields["event"])
        return f"{event.get('aggregate_type')}:{event.get('aggregate_id')}"
    except (KeyError, ValueError, AttributeError):
        return ""  # unreadable entries share one lane; _process dead-letters them


async def process_batch(entries: list[tuple[str, dict[str, str]]], concurrency: int = CONCURRENCY) -> None:
    """Process new entries: one lane per aggregate, in stream order within a lane."""
    lanes: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for entry_id, fields in entries:
        lanes[_ordering_key(fields)].append((entry_id, fields))
    limit = asyncio.Semaphore(concurrency)

    async def run(lane: list[tuple[str, dict[str, str]]]) -> None:
        async with limit:
            for entry_id, fields in lane:
                await _process(entry_id, fields)

    await asyncio.gather(*(run(lane) for lane in lanes.values()))


async def consume(stop: asyncio.Event, consumer: str | None = None, *, block_ms: int = 5000) -> None:
    from glasshaus.redis_client import get_redis

    load_handlers()
    await _ensure_group()
    redis = get_redis()
    name = consumer or f"worker-{uuid.uuid4().hex[:8]}"
    log.info("consumer.started", consumer=name)
    while not stop.is_set():
        try:
            # New events first, so a backlog of retries never delays live work.
            batches = await redis.xreadgroup(GROUP, name, {STREAM: ">"}, count=50, block=block_ms)
            for _, entries in batches or []:
                await process_batch(entries)
            # Then retry entries another (or this) consumer failed on and left idle.
            _, claimed, _ = await redis.xautoclaim(STREAM, GROUP, name, min_idle_time=RETRY_IDLE_MS, count=20)
            for entry_id, fields in claimed:
                info = await redis.xpending_range(STREAM, GROUP, min=entry_id, max=entry_id, count=1)
                await _process(entry_id, fields, info[0]["times_delivered"] if info else MAX_DELIVERIES)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("consumer.loop_error", exc_info=True)
            await asyncio.sleep(2)
    log.info("consumer.stopped", consumer=name)
