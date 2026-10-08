import pytest
from httpx import AsyncClient

from tests.factories import add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def test_saved_views(client: AsyncClient) -> None:
    world = await make_world()
    viewer = await make_user(world.tenant)
    await add_member(client, world, viewer, "viewer")
    tv = auth(await token_for(viewer))
    await create_task(client, world, title="Urgent one", priority="urgent")
    await create_task(client, world, title="Calm one", priority="low")
    base = f"/api/v1/projects/{world.project.id}/views"
    config = {"filters": {"priorities": ["urgent"]}, "group_by": "status", "columns": ["key", "title"]}

    r = await client.post(base, json={"name": "Mine", "kind": "board", "config": config}, headers=tv)
    assert r.status_code == 201
    personal = r.json()
    assert (
        await client.post(base, json={"name": "Team", "kind": "table", "shared": True}, headers=tv)
    ).status_code == 403
    shared = (
        await client.post(
            base,
            json={"name": "Team", "kind": "table", "shared": True, "config": config},
            headers=world.headers,
        )
    ).json()

    assert {v["name"] for v in (await client.get(base, headers=tv)).json()} == {"Mine", "Team"}
    assert {v["name"] for v in (await client.get(base, headers=world.headers)).json()} == {"Team"}
    assert (await client.get(f"/api/v1/views/{personal['id']}", headers=world.headers)).status_code == 404

    ran = (await client.get(f"/api/v1/views/{shared['id']}/tasks", headers=tv)).json()
    assert [t["title"] for t in ran["items"]] == ["Urgent one"]

    assert (
        await client.patch(f"/api/v1/views/{shared['id']}", json={"name": "x"}, headers=tv)
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/views/{personal['id']}", json={"shared": True}, headers=tv)
    ).status_code == 403
    r = await client.patch(f"/api/v1/views/{personal['id']}", json={"name": "Renamed"}, headers=tv)
    assert r.json()["name"] == "Renamed"
    bad = {"name": "Bad", "kind": "table", "config": {"columns": ["password"]}}
    assert (await client.post(base, json=bad, headers=tv)).status_code == 422
    assert (await client.delete(f"/api/v1/views/{personal['id']}", headers=tv)).status_code == 204
