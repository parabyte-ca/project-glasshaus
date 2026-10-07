import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from glasshaus.cli import main as cli
from glasshaus.db import get_sessionmaker
from glasshaus.models import Tenant
from glasshaus.seed import run_seed

pytestmark = pytest.mark.integration


def test_migrate_up_down_up() -> None:
    cli(["migrate"])
    cli(["downgrade", "base"])
    cli(["migrate"])


async def test_seed_is_idempotent() -> None:
    await run_seed()
    await run_seed(demo=True)
    async with get_sessionmaker()() as session:
        count = await session.scalar(select(func.count()).select_from(Tenant))
    assert count == 1


async def test_readyz_live(client: AsyncClient) -> None:
    r = await client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
