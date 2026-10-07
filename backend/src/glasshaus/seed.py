"""Idempotent seed data and demo-data generator."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.config import get_settings
from glasshaus.db import get_sessionmaker
from glasshaus.logs import get_logger
from glasshaus.models import Tenant

log = get_logger(__name__)


async def ensure_default_tenant(session: AsyncSession) -> Tenant:
    slug = get_settings().default_tenant_slug
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        tenant = Tenant(slug=slug, name="Default workspace")
        session.add(tenant)
        await session.flush()
        log.info("seed.tenant.created", slug=slug)
    return tenant


async def generate_demo_data(session: AsyncSession, tenant: Tenant, seed: int) -> None:
    """Populate realistic demo content. Domain generators are added as modules land (Phase 1+)."""
    from faker import Faker

    Faker.seed(seed)
    log.info("seed.demo.skipped", reason="no domain models yet", tenant=tenant.slug)


async def run_seed(*, demo: bool = False, seed: int = 42) -> None:
    async with get_sessionmaker()() as session, session.begin():
        tenant = await ensure_default_tenant(session)
        if demo:
            await generate_demo_data(session, tenant, seed)
