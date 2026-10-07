"""Async SQLAlchemy engine, sessions and the unit of work.

Tenant isolation: every transaction sets ``app.tenant_id`` (transaction-local) before touching
tenant data; RLS policies compare rows against it. ``app.bypass_rls`` is only set for system work
(migrations, seeding, outbox relay) and never from a request.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from glasshaus.config import get_settings
from glasshaus.core.context import Actor, ServiceContext


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def apply_tenant(
    session: AsyncSession, tenant_id: uuid.UUID | None, *, bypass_rls: bool = False
) -> None:
    """Scope the current transaction to a tenant (transaction-local settings)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.bypass_rls', :b, true)"),
        {"t": str(tenant_id) if tenant_id else "", "b": "on" if bypass_rls else "off"},
    )


@asynccontextmanager
async def unit_of_work(actor: Actor, *, bypass_rls: bool = False) -> AsyncIterator[ServiceContext]:
    """Run service calls in one transaction as ``actor``; relay domain events after commit."""
    from glasshaus.core.events import relay_events

    async with get_sessionmaker()() as session:
        async with session.begin():
            await apply_tenant(session, actor.tenant_id, bypass_rls=bypass_rls)
            ctx = ServiceContext(session=session, actor=actor)
            yield ctx
        if ctx.pending_events:
            await relay_events(ctx.pending_events)


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for system tasks only (bypasses RLS)."""
    async with get_sessionmaker()() as session, session.begin():
        await apply_tenant(session, None, bypass_rls=True)
        yield session


async def ping_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
