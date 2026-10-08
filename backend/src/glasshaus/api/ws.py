"""WebSocket endpoint for live updates."""

import asyncio
import contextlib
import uuid
from urllib.parse import urlsplit

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from glasshaus.api.deps import ACCESS_COOKIE
from glasshaus.config import get_settings
from glasshaus.core.context import Actor
from glasshaus.core.errors import NotFound, PermissionDenied, ServiceError
from glasshaus.core.events import channel_for
from glasshaus.core.rbac import Permission
from glasshaus.db import get_sessionmaker, unit_of_work
from glasshaus.identity import service as identity
from glasshaus.identity.security import API_TOKEN_PREFIX
from glasshaus.logs import get_logger
from glasshaus.realtime import VisibilityCache, to_client

router = APIRouter()
log = get_logger(__name__)


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Cookie-authenticated sockets must come from our own pages (prevents cross-site WebSocket hijacking)."""
    if not origin:
        return False
    settings = get_settings()
    allowed = {settings.public_url.rstrip("/"), *(o.rstrip("/") for o in settings.cors_origins)}
    return origin.rstrip("/") in allowed or (host is not None and urlsplit(origin).netloc == host)


async def _authenticate(websocket: WebSocket) -> Actor:
    auth = websocket.headers.get("authorization", "")
    async with get_sessionmaker()() as session, session.begin():
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token.startswith(API_TOKEN_PREFIX):
                return await identity.actor_from_api_token(session, token)
            return await identity.actor_from_access_token(session, token)
        cookie = websocket.cookies.get(ACCESS_COOKIE)
        if not cookie or not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
            raise PermissionDenied("not allowed")
        return await identity.actor_from_access_token(session, cookie)


@router.websocket("/api/v1/ws")
async def live_updates(websocket: WebSocket) -> None:
    try:
        actor = await _authenticate(websocket)
    except ServiceError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async def can_read(project_id: uuid.UUID) -> bool:
        from glasshaus.core.authz import require_project

        try:
            async with unit_of_work(actor) as ctx:
                await require_project(ctx, project_id, Permission.PROJECT_READ)
            return True
        except (NotFound, PermissionDenied):
            return False

    from glasshaus.redis_client import get_redis

    await websocket.accept()
    cache = VisibilityCache(can_read)
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel_for(actor.tenant_id))

    async def pump() -> None:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            out = await to_client(orjson.loads(message["data"]), actor, cache)
            if out is not None:
                await websocket.send_text(orjson.dumps(out).decode())

    async def receive() -> None:
        while True:
            if await websocket.receive_text() == "ping":
                await websocket.send_text('{"type":"pong"}')

    tasks = [asyncio.create_task(pump()), asyncio.create_task(receive())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        await pubsub.unsubscribe()
        await pubsub.aclose()  # type: ignore[no-untyped-call]
