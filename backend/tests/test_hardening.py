"""HTTP hardening: headers, request size, rate limits, lockout and password policy."""

import pytest
from httpx import AsyncClient

from glasshaus.identity.passwords import password_problem
from tests.factories import PASSWORD, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def test_password_policy() -> None:
    assert password_problem("password1234") is not None
    assert password_problem("abcabcabcabc") is not None
    assert password_problem("glasshaus2026") is not None
    assert password_problem("ada.lovelace99", email="ada.lovelace@example.com") is not None
    assert password_problem("violet kettle under moonlight") is None


async def test_security_headers_and_body_cap(client: AsyncClient) -> None:
    world = await make_world()
    r = await client.get("/api/v1/users/me", headers=world.headers)
    for name, value in {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "cache-control": "no-store",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    }.items():
        assert r.headers[name] == value, name
    docs = await client.get("/api/docs")
    assert "content-security-policy" not in docs.headers  # Swagger UI loads its own assets
    big = await client.post(
        "/api/v1/tasks", content=b"x" * 32, headers={**world.headers, "content-length": str(11 * 1024 * 1024)}
    )
    assert big.status_code == 413


async def test_api_rate_limit(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from glasshaus.config import get_settings

    world = await make_world()
    monkeypatch.setattr(get_settings(), "api_rate_limit_per_minute", 5)
    codes = [(await client.get("/api/v1/users/me", headers=world.headers)).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[-1] == 429
    assert (await client.get("/healthz")).status_code == 200  # health checks are never limited


async def test_account_lockout_ignores_client_ip(client: AsyncClient) -> None:
    from glasshaus.identity import service as identity

    world = await make_world()
    body = {"email": world.owner.email, "password": "not the password!", "organization": world.tenant.slug}
    codes = []
    for i in range(identity.ACCOUNT_MAX_ATTEMPTS + 1):
        r = await client.post("/api/v1/auth/login", json=body, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        codes.append(r.status_code)
    assert codes[-1] == 429
    ok = await client.post("/api/v1/auth/login", json={**body, "password": PASSWORD})
    assert ok.status_code == 429  # still locked for this window


async def test_weak_passwords_are_refused(client: AsyncClient) -> None:
    world = await make_world()
    r = await client.post(
        "/api/v1/users",
        json={"email": "weak@example.com", "name": "W", "password": "password1234"},
        headers=world.headers,
    )
    assert r.status_code == 422 and "too common" in r.text
