import pytest
from httpx import AsyncClient

from glasshaus.core.rbac import OrgRole
from tests.factories import auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def test_project_roles(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world)
    viewer, editor, outsider = [await make_user(world.tenant) for _ in range(3)]
    guest = await make_user(world.tenant, OrgRole.GUEST)
    pid = world.project.id
    for user, role in ((viewer, "viewer"), (editor, "editor"), (guest, "commenter")):
        r = await client.put(
            f"/api/v1/projects/{pid}/members",
            json={"user_id": str(user.id), "role": role},
            headers=world.headers,
        )
        assert r.status_code == 200, r.text
    tv, te, to, tg = [auth(await token_for(u)) for u in (viewer, editor, outsider, guest)]

    assert (await client.get(f"/api/v1/tasks/{task['key']}", headers=tv)).status_code == 200
    assert (
        await client.patch(f"/api/v1/tasks/{task['id']}", json={"title": "v"}, headers=tv)
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/tasks/{task['id']}", json={"title": "e"}, headers=te)
    ).status_code == 200
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=to)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}", headers=tg)).status_code == 200
    perms = (await client.get(f"/api/v1/tasks/{task['id']}/permissions", headers=tg)).json()
    assert "comment.create" in perms and "task.update" not in perms
    # Editors cannot manage members or delete the project.
    r = await client.put(
        f"/api/v1/projects/{pid}/members", json={"user_id": str(outsider.id), "role": "viewer"}, headers=te
    )
    assert r.status_code == 403
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=te)).status_code == 403


async def test_workspace_membership_grants_project_access(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    token = auth(await token_for(member))
    assert (await client.get(f"/api/v1/projects/{world.project.id}", headers=token)).status_code == 404
    r = await client.put(
        f"/api/v1/workspaces/{world.workspace_id}/members",
        json={"user_id": str(member.id), "role": "member"},
        headers=world.headers,
    )
    assert r.status_code == 200
    detail = (await client.get(f"/api/v1/projects/{world.project.id}", headers=token)).json()
    assert detail["my_role"] == "editor"
    r = await client.post(
        "/api/v1/projects",
        json={"workspace_id": str(world.workspace_id), "key": "MEMB", "name": "Mine"},
        headers=token,
    )
    assert r.status_code == 201 and r.json()["my_role"] == "admin"


async def test_guest_cannot_create_workspace(client: AsyncClient) -> None:
    world = await make_world()
    guest = await make_user(world.tenant, OrgRole.GUEST)
    r = await client.post(
        "/api/v1/workspaces", json={"name": "g", "slug": "g"}, headers=auth(await token_for(guest))
    )
    assert r.status_code == 403
