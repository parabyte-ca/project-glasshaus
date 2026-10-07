import pytest
from sqlalchemy import func, select

from glasshaus.db import system_session
from glasshaus.identity.models import User
from glasshaus.models import Task, Tenant
from glasshaus.seed import run_seed

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def test_seed_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    from glasshaus.config import get_settings

    monkeypatch.setenv("GLASSHAUS_ADMIN_PASSWORD", "seed-password-123")
    get_settings.cache_clear()
    try:
        await run_seed(demo=True)
        await run_seed(demo=True)
    finally:
        get_settings.cache_clear()
    async with system_session() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == "default"))
        assert tenant is not None
        owners = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant.id, User.org_role == "owner")
        )
        tasks = await session.scalar(
            select(func.count()).select_from(Task).where(Task.tenant_id == tenant.id)
        )
    assert owners == 1
    assert tasks and tasks > 30
