"""Request authentication and the per-request service context."""

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import PermissionDenied, Unauthenticated
from glasshaus.core.events import relay_events
from glasshaus.db import get_sessionmaker
from glasshaus.identity import service as identity
from glasshaus.identity.security import API_TOKEN_PREFIX

ACCESS_COOKIE = "gh_access"
REFRESH_COOKIE = "gh_refresh"
CSRF_COOKIE = "gh_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def _authenticate(request: Request, session: AsyncSession) -> ServiceContext:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith(API_TOKEN_PREFIX):
            actor = await identity.actor_from_api_token(session, token)
        else:
            actor = await identity.actor_from_access_token(session, token)
        return ServiceContext(session=session, actor=actor)
    cookie = request.cookies.get(ACCESS_COOKIE)
    if not cookie:
        raise Unauthenticated("authentication required")
    if request.method not in SAFE_METHODS:
        expected = request.cookies.get(CSRF_COOKIE, "")
        provided = request.headers.get(CSRF_HEADER, "")
        if not expected or not secrets.compare_digest(expected, provided):
            raise PermissionDenied("CSRF token missing or invalid")
    actor = await identity.actor_from_access_token(session, cookie)
    return ServiceContext(session=session, actor=actor)


async def get_ctx(request: Request) -> AsyncIterator[ServiceContext]:
    """Authenticate, open one transaction for the request, commit before the response is sent."""
    async with get_sessionmaker()() as session:
        async with session.begin():
            ctx = await _authenticate(request, session)
            yield ctx
        if ctx.pending_events:
            await relay_events(ctx.pending_events)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Unauthenticated transaction (login/refresh/logout)."""
    async with get_sessionmaker()() as session, session.begin():
        yield session


Ctx = Annotated[ServiceContext, Depends(get_ctx, scope="function")]
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]
