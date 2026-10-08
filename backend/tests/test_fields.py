from typing import Any

import pytest
from httpx import AsyncClient

from tests.factories import add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def _field(client: AsyncClient, world, **body):  # type: ignore[no-untyped-def]
    r = await client.post(f"/api/v1/projects/{world.project.id}/fields", json=body, headers=world.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_select_field_values_filter_and_sort(client: AsyncClient) -> None:
    world = await make_world()
    sev = await _field(
        client,
        world,
        name="Severity",
        type="select",
        options=[{"id": "s1", "label": "Sev 1"}, {"id": "s2", "label": "Sev 2"}],
    )
    pts = await _field(client, world, name="Points", type="number")
    a = await create_task(client, world, title="A", custom_fields={sev["id"]: "s1", pts["id"]: 5})
    b = await create_task(client, world, title="B", custom_fields={sev["id"]: "s2", pts["id"]: 3})
    assert a["custom_fields"] == {sev["id"]: "s1", pts["id"]: 5}

    r = await client.post(
        "/api/v1/tasks",
        headers=world.headers,
        json={"project_id": str(world.project.id), "title": "bad", "custom_fields": {sev["id"]: "nope"}},
    )
    assert r.status_code == 422 and "unknown option" in r.json()["detail"]
    r = await client.patch(
        f"/api/v1/tasks/{a['id']}", json={"custom_fields": {pts["id"]: "five"}}, headers=world.headers
    )
    assert r.status_code == 422

    async def titles(**params: Any) -> list[str]:
        r = await client.get(
            "/api/v1/tasks", params={"project_id": str(world.project.id), **params}, headers=world.headers
        )
        assert r.status_code == 200, r.text
        return [t["title"] for t in r.json()["items"]]

    assert await titles(cf=[f"{sev['id']}=s2"]) == ["B"]
    assert await titles(cf=[f"{pts['id']}=5"]) == ["A"]
    assert await titles(sort_field=pts["id"]) == ["B", "A"]

    # Removing an option clears it from tasks; other values stay.
    r = await client.patch(
        f"/api/v1/projects/{world.project.id}/fields/{sev['id']}",
        json={"options": [{"id": "s1", "label": "Sev 1"}]},
        headers=world.headers,
    )
    assert r.status_code == 200
    got = (await client.get(f"/api/v1/tasks/{b['id']}", headers=world.headers)).json()
    assert got["custom_fields"] == {pts["id"]: 3}

    assert (
        await client.delete(f"/api/v1/projects/{world.project.id}/fields/{pts['id']}", headers=world.headers)
    ).status_code == 204
    got = (await client.get(f"/api/v1/tasks/{a['id']}", headers=world.headers)).json()
    assert got["custom_fields"] == {sev["id"]: "s1"}


async def test_multi_select_user_and_required(client: AsyncClient) -> None:
    world = await make_world()
    labels = await _field(
        client,
        world,
        name="Labels",
        type="multi_select",
        options=[{"id": "ux", "label": "UX"}, {"id": "api", "label": "API"}],
    )
    owner = await _field(client, world, name="Owner", type="user", required=True)
    r = await client.post(
        "/api/v1/tasks", headers=world.headers, json={"project_id": str(world.project.id), "title": "x"}
    )
    assert r.status_code == 422 and "Owner" in r.json()["detail"]
    task = await create_task(
        client, world, custom_fields={labels["id"]: ["api", "ux", "api"], owner["id"]: str(world.owner.id)}
    )
    assert task["custom_fields"][labels["id"]] == ["api", "ux"]
    r = await client.get(
        "/api/v1/tasks",
        params={"project_id": str(world.project.id), "cf": f"{labels['id']}=ux"},
        headers=world.headers,
    )
    assert [t["id"] for t in r.json()["items"]] == [task["id"]]
    r = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"custom_fields": {owner["id"]: None}}, headers=world.headers
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/api/v1/projects/{world.project.id}/fields/{labels['id']}",
        json={"options": [{"id": "ux", "label": "UX"}]},
        headers=world.headers,
    )
    got = (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()
    assert got["custom_fields"][labels["id"]] == ["ux"]


async def test_editors_cannot_define_fields(client: AsyncClient) -> None:
    world = await make_world()
    editor = await make_user(world.tenant)
    await add_member(client, world, editor, "editor")
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/fields",
        json={"name": "X", "type": "text"},
        headers=auth(await token_for(editor)),
    )
    assert r.status_code == 403
