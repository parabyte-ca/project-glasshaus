"""SCIM 2.0 provisioning (the requests Okta, Entra ID and Authentik send)."""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.factories import PASSWORD, World, auth, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]
SCIM = "application/scim+json"


async def scim_token(client: AsyncClient, world: World) -> dict[str, str]:
    r = await client.post("/api/v1/admin/scim-tokens", json={"name": "Entra ID"}, headers=world.headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("ghs_") and body["base_url"].endswith("/scim/v2")
    return {**auth(body["token"]), "Content-Type": SCIM}


async def test_discovery_and_auth(client: AsyncClient) -> None:
    world = await make_world()
    assert (await client.get("/scim/v2/ServiceProviderConfig")).json()["patch"]["supported"] is True
    types = (await client.get("/scim/v2/ResourceTypes")).json()
    assert {t["id"] for t in types["Resources"]} == {"User", "Group"}
    r = await client.get("/scim/v2/Users")
    assert r.status_code == 401 and r.headers["content-type"].startswith(SCIM)
    assert r.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert (
        await client.get("/scim/v2/Users", headers=world.headers)
    ).status_code == 401  # API tokens don't work


async def test_user_lifecycle(client: AsyncClient) -> None:
    world, other = await make_world(), await make_world()
    h = await scim_token(client, world)
    body: dict[str, Any] = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "grace@example.com",
        "externalId": "00u123",
        "name": {"givenName": "Grace", "familyName": "Hopper"},
        "emails": [{"value": "grace@example.com", "primary": True}],
        "active": True,
    }
    r = await client.post("/scim/v2/Users", json=body, headers=h)
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["displayName"] == "Grace Hopper" and user["active"] is True and user["externalId"] == "00u123"
    assert (await client.post("/scim/v2/Users", json=body, headers=h)).json()["scimType"] == "uniqueness"

    found = (
        await client.get("/scim/v2/Users", params={"filter": 'userName eq "GRACE@example.com"'}, headers=h)
    ).json()
    assert found["totalResults"] == 1 and found["Resources"][0]["id"] == user["id"]
    by_ext = (
        await client.get("/scim/v2/Users", params={"filter": 'externalId eq "00u123"'}, headers=h)
    ).json()
    assert by_ext["totalResults"] == 1
    bad = await client.get("/scim/v2/Users", params={"filter": 'title co "x"'}, headers=h)
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidFilter"

    # The other organization's SCIM token cannot see or touch this user.
    h_other = await scim_token(client, other)
    assert (await client.get(f"/scim/v2/Users/{user['id']}", headers=h_other)).status_code == 404

    # The provisioned user can sign in once a password exists (or with SSO); deactivation ends sessions.
    # Give the provisioned account a password (admins need a browser session for this).
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": world.owner.email, "password": PASSWORD, "organization": world.tenant.slug},
    )
    csrf = {"X-CSRF-Token": client.cookies["gh_csrf"]}
    r = await client.post(
        f"/api/v1/admin/users/{user['id']}/password", json={"new_password": PASSWORD}, headers=csrf
    )
    assert r.status_code == 204
    client.cookies.clear()
    await client.post(
        "/api/v1/auth/login",
        json={"email": "grace@example.com", "password": PASSWORD, "organization": world.tenant.slug},
    )
    assert (await client.get("/api/v1/users/me")).status_code == 200

    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"active": False}}],
    }
    r = await client.patch(f"/scim/v2/Users/{user['id']}", json=patch, headers=h)
    assert r.status_code == 200 and r.json()["active"] is False
    assert (await client.get("/api/v1/users/me")).status_code == 401
    client.cookies.clear()

    # Entra-style path patch and full replace.
    patch = {"Operations": [{"op": "Replace", "path": "active", "value": "True"},
                            {"op": "replace", "path": "displayName", "value": "Rear Admiral Hopper"}]}  # fmt: skip
    r = await client.patch(f"/scim/v2/Users/{user['id']}", json=patch, headers=h)
    assert r.json()["active"] is True and r.json()["displayName"] == "Rear Admiral Hopper"
    r = await client.put(f"/scim/v2/Users/{user['id']}", json={**body, "userName": "g.hopper@example.com",
                                                                "emails": [], "displayName": "G"}, headers=h)  # fmt: skip
    assert r.json()["userName"] == "g.hopper@example.com"

    # DELETE disables (history is kept).
    assert (await client.delete(f"/scim/v2/Users/{user['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/scim/v2/Users/{user['id']}", headers=h)).json()["active"] is False
    # Owners are never deactivated through SCIM.
    r = await client.patch(f"/scim/v2/Users/{world.owner.id}", json=patch | {"Operations": [{"op": "replace", "path": "active", "value": False}]}, headers=h)  # fmt: skip
    assert r.status_code == 400


async def test_groups_map_to_workspaces(client: AsyncClient) -> None:
    world = await make_world()
    h = await scim_token(client, world)
    a = (await client.post("/scim/v2/Users", json={"userName": "a@example.com"}, headers=h)).json()
    b = (await client.post("/scim/v2/Users", json={"userName": "b@example.com"}, headers=h)).json()
    r = await client.post(
        "/scim/v2/Groups", json={"displayName": "Engineering", "members": [{"value": a["id"]}]}, headers=h
    )
    assert r.status_code == 201, r.text
    group = r.json()
    ws = (await client.get("/api/v1/workspaces", headers=world.headers)).json()
    assert "Engineering" in {w["name"] for w in ws}

    add = {"Operations": [{"op": "add", "path": "members", "value": [{"value": b["id"]}]}]}
    r = await client.patch(f"/scim/v2/Groups/{group['id']}", json=add, headers=h)
    assert {m["value"] for m in r.json()["members"]} == {a["id"], b["id"]}
    remove = {"Operations": [{"op": "remove", "path": f'members[value eq "{a["id"]}"]'}]}
    r = await client.patch(f"/scim/v2/Groups/{group['id']}", json=remove, headers=h)
    assert [m["value"] for m in r.json()["members"]] == [b["id"]]
    bad = {"Operations": [{"op": "add", "path": "members", "value": [{"value": "not-a-user"}]}]}
    assert (await client.patch(f"/scim/v2/Groups/{group['id']}", json=bad, headers=h)).status_code == 404
    listed = (
        await client.get("/scim/v2/Groups", params={"filter": 'displayName eq "Engineering"'}, headers=h)
    ).json()
    assert listed["totalResults"] == 1
    assert (await client.delete(f"/scim/v2/Groups/{group['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/scim/v2/Groups/{group['id']}", headers=h)).json()["members"] == []


async def test_revoked_token_stops_working(client: AsyncClient) -> None:
    world = await make_world()
    h = await scim_token(client, world)
    token_id = (await client.get("/api/v1/admin/scim-tokens", headers=world.headers)).json()[0]["id"]
    assert (
        await client.delete(f"/api/v1/admin/scim-tokens/{token_id}", headers=world.headers)
    ).status_code == 204
    assert (await client.get("/scim/v2/Users", headers=h)).status_code == 401
