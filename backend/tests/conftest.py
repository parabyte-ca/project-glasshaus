import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("GLASSHAUS_ENV", "test")
os.environ.setdefault("GLASSHAUS_LOG_JSON", "false")
os.environ.setdefault("GLASSHAUS_SECRET_KEY", "test-secret-key-0123456789abcdef-0123456789")

from glasshaus.main import create_app


def integration_enabled() -> bool:
    return os.getenv("GLASSHAUS_INTEGRATION", "0") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if integration_enabled():
        return
    skip = pytest.mark.skip(reason="set GLASSHAUS_INTEGRATION=1 with Postgres and Redis available")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def migrated() -> None:
    from glasshaus.cli import main as cli

    cli(["migrate"])
