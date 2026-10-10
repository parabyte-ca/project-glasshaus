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
    # AGPL-3.0 section 13: anyone using the server can find its source.
    assert r.json()["license"] == "AGPL-3.0-only" and r.json()["source"].startswith("https://")


async def test_third_party_licences_are_listed_without_signing_in(client: AsyncClient) -> None:
    r = await client.get("/api/v1/licenses")
    assert r.status_code == 200
    names = {p["name"].lower(): p for p in r.json()}
    assert "fastapi" in names and names["fastapi"]["license"]


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


def test_openapi_document_is_committed(app) -> None:  # type: ignore[no-untyped-def]
    """docs/openapi.json is the published contract; regenerate with `make openapi`."""
    import json
    from pathlib import Path

    committed = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    if not committed.exists():
        pytest.skip("not running from a full checkout")
    assert json.loads(committed.read_text()) == app.openapi(), "OpenAPI drift: run `make openapi`"


def test_operation_ids_unique(app) -> None:  # type: ignore[no-untyped-def]
    ops = [op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()]
    assert len(ops) == len(set(ops))


def test_worker_process_registers_every_model() -> None:
    """The worker never imports the web app; loading handlers must still register all tables."""
    import subprocess
    import sys

    code = (
        "from glasshaus.core.consumers import load_handlers; load_handlers();"
        "from glasshaus.core.orm import RLS_TABLES, Base;"
        "missing = {'tenants', *RLS_TABLES} - set(Base.metadata.tables); assert not missing, missing"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_mcp_process_registers_every_model() -> None:
    """The MCP server runs without the web app; importing it must register all tables (FK targets)."""
    import os
    import subprocess
    import sys

    code = (
        "import glasshaus.mcp_server.server;"
        "from glasshaus.core.orm import RLS_TABLES, Base;"
        "missing = {'tenants', 'oauth_grants', *RLS_TABLES} - set(Base.metadata.tables); assert not missing, missing"
    )
    env = {**os.environ, "GLASSHAUS_ENV": "test", "GLASSHAUS_SECRET_KEY": "x" * 40}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, env=env
    )
    assert result.returncode == 0, result.stderr
