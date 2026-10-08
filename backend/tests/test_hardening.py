"""HTTP hardening: headers, request size, rate limits, lockout and password policy."""

import uuid
from collections.abc import AsyncIterator

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

    # A chunked body without Content-Length is counted as it streams (no buffering of huge uploads).
    async def chunks(parts: list[bytes]) -> AsyncIterator[bytes]:
        for part in parts:
            yield part

    streamed = await client.post(
        "/api/v1/auth/login",
        content=chunks([b"x" * (1024 * 1024)] * 11),
        headers={"content-type": "application/json"},
    )
    assert streamed.status_code == 413 and streamed.json()["code"] == "payload_too_large"
    # Small chunked bodies still reach the app intact.
    body = b'{"email": "nobody@example.com", ' + b'"password": "wrong password here"}'
    small = await client.post(
        "/api/v1/auth/login",
        content=chunks([body[:10], body[10:]]),
        headers={"content-type": "application/json"},
    )
    assert small.status_code == 401


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


async def test_forwarded_for_only_from_trusted_proxies() -> None:
    from starlette.types import Receive, Scope, Send

    from glasshaus.api.proxy import ProxyHeadersMiddleware, TrustedProxies

    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["client"][0])

    middleware = ProxyHeadersMiddleware(app)
    middleware.trusted = TrustedProxies(["10.9.0.0/24", "localhost"])

    async def call(peer: str, forwarded: str | None) -> str:
        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        await middleware({"type": "http", "client": (peer, 1), "headers": headers}, None, None)  # type: ignore[arg-type]
        return seen[-1]

    # The trusted proxy's own (right-most) entry wins; anything the client prepended is ignored.
    assert await call("10.9.0.5", "6.6.6.6, 198.51.100.7") == "198.51.100.7"
    assert await call("127.0.0.1", "198.51.100.8") == "198.51.100.8"  # hostname resolved
    # Direct clients cannot choose their address.
    assert await call("203.0.113.9", "10.0.0.1") == "203.0.113.9"
    assert await call("10.9.0.5", "not-an-ip") == "10.9.0.5"
    assert await call("10.9.0.5", None) == "10.9.0.5"


async def test_rate_limit_counts_client_address_too(app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """Inventing a new Authorization header per request does not escape the limit."""
    from httpx import ASGITransport

    from glasshaus.api import hardening
    from glasshaus.config import get_settings

    monkeypatch.setattr(get_settings(), "api_rate_limit_per_minute", 2)
    transport = ASGITransport(app=app, client=(f"203.0.113.{uuid.uuid4().int % 250}", 4000))
    async with AsyncClient(transport=transport, base_url="http://test") as direct:
        codes = [
            (await direct.get("/api/v1/users/me", headers={"Authorization": f"Bearer junk-{i}"})).status_code
            for i in range(2 * hardening.PER_ADDRESS_FACTOR + 2)
        ]
    assert codes[0] == 401 and codes[-1] == 429
