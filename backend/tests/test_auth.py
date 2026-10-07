import pytest
from httpx import AsyncClient

from glasshaus.core.rbac import OrgRole, Scope
from glasshaus.redis_client import get_redis
from tests.factories import PASSWORD, auth, make_tenant, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def _login(client: AsyncClient, email: str, org: str, password: str = PASSWORD) -> int:
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password, "organization": org}
    )
    return r.status_code


async def test_unauthenticated_is_problem_json(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "unauthenticated"


async def test_cookie_session_flow_with_csrf(client: AsyncClient) -> None:
    tenant = await make_tenant()
    user = await make_user(tenant, OrgRole.ADMIN)
    assert await _login(client, user.email.upper(), tenant.slug, "wrong password!") == 401
    assert await _login(client, user.email.upper(), tenant.slug) == 200
    assert {"gh_access", "gh_refresh", "gh_csrf"} <= set(client.cookies.keys())

    me = await client.get("/api/v1/users/me")
    assert me.status_code == 200 and me.json()["id"] == str(user.id)

    body = {"name": "WS", "slug": "ws"}
    assert (await client.post("/api/v1/workspaces", json=body)).status_code == 403  # no CSRF header
    csrf = client.cookies["gh_csrf"]
    assert (
        await client.post("/api/v1/workspaces", json=body, headers={"X-CSRF-Token": csrf})
    ).status_code == 201

    old_refresh = client.cookies["gh_refresh"]
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    assert client.cookies["gh_refresh"] != old_refresh
    # A rotated refresh token is dead.
    new_refresh = client.cookies["gh_refresh"]
    client.cookies.set("gh_refresh", old_refresh, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    client.cookies.set("gh_refresh", new_refresh, path="/api/v1/auth")

    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_login_rate_limited(client: AsyncClient) -> None:
    tenant = await make_tenant()
    user = await make_user(tenant)
    await get_redis().delete(f"glasshaus:login:127.0.0.1:{user.email}")
    codes = [await _login(client, user.email, tenant.slug, "nope nope nope") for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


async def test_token_scopes_and_revocation(client: AsyncClient) -> None:
    world = await make_world()
    read_only = await token_for(world.owner, (Scope.READ,))
    body = {"project_id": str(world.project.id), "title": "x"}
    assert (await client.get("/api/v1/tasks", headers=auth(read_only))).status_code == 200
    r = await client.post("/api/v1/tasks", json=body, headers=auth(read_only))
    assert r.status_code == 403 and "scope" in r.json()["detail"]

    writer = await token_for(world.owner, (Scope.TASKS_WRITE,))
    assert (await client.post("/api/v1/tasks", json=body, headers=auth(writer))).status_code == 201

    tokens = (await client.get("/api/v1/tokens", headers=world.headers)).json()
    writer_id = next(t["id"] for t in tokens if t["scopes"] == ["tasks:write"])
    assert (await client.delete(f"/api/v1/tokens/{writer_id}", headers=world.headers)).status_code == 204
    assert (await client.post("/api/v1/tasks", json=body, headers=auth(writer))).status_code == 401
    assert (await client.get("/api/v1/tasks", headers=auth("ghp_not-a-real-token"))).status_code == 401


async def test_members_cannot_mint_admin_tokens(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    token = await token_for(member)
    r = await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["admin"]}, headers=auth(token))
    assert r.status_code == 403
