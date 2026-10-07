"""Row-level security: one tenant can never read or write another tenant's rows."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from glasshaus.db import apply_tenant, get_sessionmaker
from glasshaus.dbroles import check_least_privilege
from glasshaus.models import RLS_TABLES, Task
from tests.factories import create_task, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def test_app_role_is_subject_to_rls() -> None:
    assert await check_least_privilege(), "tests must connect as a role without SUPERUSER/BYPASSRLS"


async def test_rls_tables_have_policies() -> None:
    async with get_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relkind = 'r'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert set(RLS_TABLES) <= set(rows)


async def test_cross_tenant_isolation(client: AsyncClient) -> None:
    a, b = await make_world(), await make_world()
    task = await create_task(client, a, title="secret")

    r = await client.get(f"/api/v1/tasks/{task['id']}", headers=b.headers)
    assert r.status_code == 404
    r = await client.get("/api/v1/tasks", params={"q": "secret"}, headers=b.headers)
    assert r.json()["items"] == []
    r = await client.get(f"/api/v1/projects/{a.project.id}", headers=b.headers)
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/tasks", json={"project_id": str(a.project.id), "title": "x"}, headers=b.headers
    )
    assert r.status_code == 404

    # Even raw SQL without a tenant filter sees nothing from tenant A when scoped to B ...
    async with get_sessionmaker()() as session, session.begin():
        await apply_tenant(session, b.tenant.id)
        assert await session.scalar(select(func.count()).select_from(Task).where(Task.title == "secret")) == 0
    # ... and nothing at all when no tenant is set (default deny).
    async with get_sessionmaker()() as session, session.begin():
        await apply_tenant(session, None)
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
