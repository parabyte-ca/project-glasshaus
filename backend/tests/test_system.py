import pytest
from httpx import AsyncClient

from glasshaus import __version__
from glasshaus.api import health


async def test_healthz(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_version(client: AsyncClient) -> None:
    r = await client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json()["version"] == __version__


async def test_openapi_is_3_1(client: AsyncClient) -> None:
    r = await client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert r.json()["openapi"].startswith("3.1")


async def test_metrics_exposed(client: AsyncClient) -> None:
    await client.get("/healthz")
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "glasshaus_http_requests_total" in r.text


async def test_readyz_reports_failures(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> None:
        return None

    async def broken() -> None:
        raise ConnectionError

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "ping_redis", broken)
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"] == {"database": "ok", "redis": "error: ConnectionError"}


def test_version_matches_repo_file() -> None:
    from pathlib import Path

    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    if version_file.exists():
        assert version_file.read_text().strip() == __version__
