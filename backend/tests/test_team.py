"""Reporting lines (SCIM and Microsoft Graph) and the My team page."""

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from glasshaus.db import apply_tenant, system_session
from glasshaus.identity.models import User
from glasshaus.people import graph
from tests.factories import World, add_member, auth, create_task, make_user, make_world, token_for
from tests.test_governance import audit
from tests.test_scim import scim_token

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


async def report_to(world: World, person: User, manager: User | None, source: str = "scim") -> None:
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        await session.execute(
            update(User)
            .where(User.id == person.id)
            .values(manager_id=manager.id if manager else None, manager_source=source)
        )


async def test_scim_sends_managers_titles_and_departments(client: AsyncClient) -> None:
    world = await make_world()
    h = await scim_token(client, world)
    types = (await client.get("/scim/v2/ResourceTypes")).json()["Resources"]
    user_type = next(t for t in types if t["id"] == "User")
    assert user_type["schemaExtensions"][0]["schema"] == ENTERPRISE

    def person(name: str, **extra: Any) -> dict[str, Any]:
        return {"userName": f"{name}-{uuid.uuid4().hex[:6]}@example.com", "displayName": name, **extra}

    boss = (await client.post("/scim/v2/Users", json=person("Boss"), headers=h)).json()
    body = person(
        "Ada", title="Engineer", **{ENTERPRISE: {"department": "R&D", "manager": {"value": boss["id"]}}}
    )
    ada = (await client.post("/scim/v2/Users", json=body, headers=h)).json()
    assert ada["title"] == "Engineer" and ada[ENTERPRISE] == {
        "department": "R&D",
        "manager": {"value": boss["id"]},
    }

    # Entra ID's PATCH: the manager as a path with a bare id, then removed.
    lin = (await client.post("/scim/v2/Users", json=person("Lin"), headers=h)).json()
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "Add", "path": f"{ENTERPRISE}:manager", "value": ada["id"]},
            {"op": "Replace", "path": "title", "value": "Analyst"},
        ],
    }
    r = await client.patch(f"/scim/v2/Users/{lin['id']}", json=patch, headers=h)
    assert r.status_code == 200 and r.json()[ENTERPRISE]["manager"]["value"] == ada["id"]
    assert r.json()["title"] == "Analyst"

    # A loop is refused (the boss cannot report to someone below them); the rest still applies.
    loop = {"op": "Replace", "path": f"{ENTERPRISE}:manager", "value": {"value": lin["id"]}}
    r = await client.patch(f"/scim/v2/Users/{boss['id']}", json=patch | {"Operations": [loop]}, headers=h)
    assert r.status_code == 200 and ENTERPRISE not in r.json()

    remove = {"op": "Remove", "path": f"{ENTERPRISE}:manager"}
    r = await client.patch(f"/scim/v2/Users/{lin['id']}", json=patch | {"Operations": [remove]}, headers=h)
    assert ENTERPRISE not in r.json()


async def test_managers_see_their_team_and_opening_tasks_is_audited(client: AsyncClient) -> None:
    world = await make_world()
    manager = await make_user(world.tenant)  # not a member of the project
    ada = await make_user(world.tenant)
    lin = await make_user(world.tenant)  # reports to Ada
    stranger = await make_user(world.tenant)
    await add_member(client, world, ada, "editor")
    await add_member(client, world, lin, "editor")
    await report_to(world, ada, manager)
    await report_to(world, lin, ada)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    late = await create_task(client, world, title="Late report", assignee_id=str(ada.id), due_date=yesterday)
    await create_task(client, world, title="Plan", assignee_id=str(ada.id))
    await create_task(client, world, title="Lin's work", assignee_id=str(lin.id))
    r = await client.post(
        "/api/v1/time-entries",
        json={"task": late["id"], "minutes": 90, "spent_on": date.today().isoformat()},
        headers=auth(await token_for(ada)),
    )
    assert r.status_code == 201, r.text

    mh = auth(await token_for(manager))
    me = (await client.get("/api/v1/users/me", headers=mh)).json()
    assert me["direct_reports"] == 1
    team = (await client.get("/api/v1/team", headers=mh)).json()
    assert team["visibility"] == "all" and team["direct_reports"] == 1
    [row] = team["people"]
    assert row["id"] == str(ada.id) and row["level"] == 1
    assert (row["open"], row["overdue"], row["logged_this_week"]) == (2, 1, 90)
    assert row["projects"][0]["key"] == world.project.key and row["projects"][0]["visible"] is False
    everyone = (await client.get("/api/v1/team", params={"everyone": True}, headers=mh)).json()
    assert [(p["id"], p["level"]) for p in everyone["people"]] == [(str(ada.id), 1), (str(lin.id), 2)]

    # Full detail in every project (the default), and the manager opening it is audited.
    tasks = (await client.get(f"/api/v1/team/{ada.id}/tasks", headers=mh)).json()
    assert [t["title"] for t in tasks["tasks"]] == ["Late report", "Plan"] and tasks["hidden"] == 0
    assert (await audit(world, "team.tasks_viewed"))[-1].actor_id == manager.id
    assert (await client.get(f"/api/v1/team/{lin.id}/tasks", headers=mh)).status_code == 200
    r = await client.get(f"/api/v1/team/{stranger.id}/tasks", headers=mh)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/team/{manager.id}/tasks", headers=auth(await token_for(ada)))
    assert r.status_code == 404  # not upwards

    # "Shared" visibility: only projects the manager can open; elsewhere counts.
    r = await client.patch(
        "/api/v1/admin/settings", json={"manager_visibility": "shared"}, headers=world.headers
    )
    assert r.status_code == 200 and r.json()["manager_visibility"] == "shared"
    team = (await client.get("/api/v1/team", headers=mh)).json()
    project = team["people"][0]["projects"][0]
    assert team["visibility"] == "shared" and project["key"] is None and project["open_tasks"] == 2
    tasks = (await client.get(f"/api/v1/team/{ada.id}/tasks", headers=mh)).json()
    assert tasks["tasks"] == [] and tasks["hidden"] == 2


async def test_graph_sync_fills_in_managers_scim_does_not_send(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await make_world()
    boss = await make_user(world.tenant, email=f"boss-{uuid.uuid4().hex[:6]}@example.com")
    ada = await make_user(world.tenant, email=f"ada-{uuid.uuid4().hex[:6]}@example.com")
    lin = await make_user(world.tenant, email=f"lin-{uuid.uuid4().hex[:6]}@example.com")
    await report_to(world, lin, ada, source="scim")  # SCIM wins over Graph

    url = "/api/v1/admin/directory-sync"
    bad = {"enabled": True, "directory_id": "contoso.onmicrosoft.com", "client_id": "abc"}
    assert (await client.put(url, json=bad, headers=world.headers)).status_code == 422
    assert (
        await client.put(url, json=bad | {"directory_id": "../evil"}, headers=world.headers)
    ).status_code == 422
    r = await client.put(url, json=bad | {"client_secret": "s3cret"}, headers=world.headers)
    assert r.status_code == 200 and r.json()["client_secret"] == "••••••••" and r.json()["enabled"]
    member = await make_user(world.tenant)
    assert (await client.get(url, headers=auth(await token_for(member)))).status_code == 403

    seen: dict[str, str] = {}

    async def fake_directory(directory_id: str, client_id: str, secret: str) -> list[dict[str, Any]]:
        seen.update(directory=directory_id, secret=secret)
        return [
            {
                "id": "g-boss",
                "emails": {boss.email.upper().lower()},
                "job_title": "CEO",
                "department": None,
                "manager": None,
            },
            {
                "id": "g-ada",
                "emails": {ada.email},
                "job_title": "Lead",
                "department": "Ops",
                "manager": "g-boss",
            },
            {
                "id": "g-lin",
                "emails": {lin.email},
                "job_title": "Analyst",
                "department": None,
                "manager": "g-boss",
            },
            {
                "id": "g-ghost",
                "emails": {"ghost@elsewhere.example"},
                "job_title": None,
                "department": None,
                "manager": "g-boss",
            },
        ]

    monkeypatch.setattr(graph, "fetch_directory", fake_directory)
    r = await client.post(f"{url}/run", headers=world.headers)
    assert r.status_code == 200, r.text
    assert r.json()["last_error"] is None and r.json()["last_result"]["managers"] == 1
    assert seen == {"directory": "contoso.onmicrosoft.com", "secret": "s3cret"}  # decrypted for the call
    users = {u["id"]: u for u in (await client.get("/api/v1/users", headers=world.headers)).json()}
    assert users[str(ada.id)]["manager_id"] == str(boss.id) and users[str(ada.id)]["department"] == "Ops"
    assert users[str(lin.id)]["manager_id"] == str(ada.id)  # left as SCIM set it
    assert (await client.post(f"{url}/run", headers=world.headers)).status_code == 429  # once a minute

    async def failing(*_: str) -> list[dict[str, Any]]:
        raise graph.SyncError("the app needs the User.Read.All application permission (admin consent)")

    monkeypatch.setattr(graph, "fetch_directory", failing)
    with pytest.raises(graph.SyncError):
        await graph.sync(world.tenant.id)
    r = await client.get(url, headers=world.headers)
    assert "User.Read.All" in r.json()["last_error"]
