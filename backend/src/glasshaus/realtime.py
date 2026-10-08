"""Realtime fan-out: per-tenant Redis pub/sub -> WebSocket clients.

Clients receive only identifiers (event type, aggregate, project) for things they can see, then refetch
through the normal authorized API. No payload data crosses the socket.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import orjson

from glasshaus.core.context import Actor
from glasshaus.core.events import channel_for

VISIBILITY_TTL_SECONDS = 60
MEMBERSHIP_EVENTS = frozenset(
    {
        "project.member_set",
        "project.member_removed",
        "workspace.member_set",
        "workspace.member_removed",
        "project.deleted",
        "user.updated",
    }
)


async def publish_user_signal(tenant_id: uuid.UUID, user_ids: list[str], signal_type: str) -> None:
    from glasshaus.redis_client import get_redis

    body = orjson.dumps({"type": signal_type, "signal": True, "user_ids": user_ids}).decode()
    await get_redis().publish(channel_for(tenant_id), body)


class VisibilityCache:
    """Remembers which projects a connected actor may read, for a short time."""

    def __init__(
        self, check: Callable[[uuid.UUID], Awaitable[bool]], ttl: float = VISIBILITY_TTL_SECONDS
    ) -> None:
        self._check = check
        self._ttl = ttl
        self._cache: dict[uuid.UUID, tuple[bool, float]] = {}

    def clear(self) -> None:
        self._cache.clear()

    async def visible(self, project_id: uuid.UUID) -> bool:
        hit = self._cache.get(project_id)
        now = time.monotonic()
        if hit and hit[1] > now:
            return hit[0]
        allowed = await self._check(project_id)
        self._cache[project_id] = (allowed, now + self._ttl)
        return allowed


async def to_client(message: dict[str, Any], actor: Actor, cache: VisibilityCache) -> dict[str, Any] | None:
    """Decide what (if anything) a connected actor receives for one pub/sub message."""
    if message.get("signal"):
        if actor.user_id and str(actor.user_id) in message.get("user_ids", []):
            return {"type": message["type"]}
        return None
    if message.get("type") in MEMBERSHIP_EVENTS:
        cache.clear()
    raw_project = message.get("project_id")
    if raw_project is None:
        actor_id = (message.get("actor") or {}).get("user_id")
        if actor.user_id is None or actor_id != str(actor.user_id):
            return None
    elif not await cache.visible(uuid.UUID(raw_project)):
        return None
    return {
        "id": message.get("id"),
        "type": message.get("type"),
        "aggregate_type": message.get("aggregate_type"),
        "aggregate_id": message.get("aggregate_id"),
        "project_id": raw_project,
    }
