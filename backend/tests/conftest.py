import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("GLASSHAUS_ENV", "test")
os.environ.setdefault("GLASSHAUS_LOG_JSON", "false")

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


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c
