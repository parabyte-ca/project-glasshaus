import asyncio
import uuid

import pytest
from httpx import AsyncClient

from glasshaus.core.consumers import consume, dispatch, load_handlers
from tests.factories import add_member, auth, create_task, events_for, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def mention(user) -> str:  # type: ignore[no-untyped-def]
    return f"@[{user.name}](user:{user.id})"


async def test_comments_permissions_and_mentions(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world)
    viewer, commenter = await make_user(world.tenant), await make_user(world.tenant)
    await add_member(client, world, viewer, "viewer")
    await add_member(client, world, commenter, "commenter")
    tv, tc = auth(await token_for(viewer)), auth(await token_for(commenter))
    url = f"/api/v1/tasks/{task['key']}/comments"

    assert (await client.post(url, json={"body": "hi"}, headers=tv)).status_code == 403
    body = f"Thoughts {mention(viewer)}? cc @{world.owner.email} and @nobody@example.com"
    r = await client.post(url, json={"body": body}, headers=tc)
    assert r.status_code == 201
    comment = r.json()
    assert set(comment["mentions"]) == {str(viewer.id), str(world.owner.id)}

    listed = (await client.get(url, headers=tv)).json()
    assert [c["id"] for c in listed] == [comment["id"]]
    curl = f"/api/v1/comments/{comment['id']}"
    assert (await client.patch(curl, json={"body": "edit"}, headers=world.headers)).status_code == 403
    edited = await client.patch(curl, json={"body": "edited"}, headers=tc)
    assert edited.json()["edited_at"] is not None and edited.json()["mentions"] == []
    # Project admins can moderate.
    assert (await client.delete(curl, headers=world.headers)).status_code == 204
    assert (await client.get(url, headers=tc)).json() == []


async def test_notifications_from_events(client: AsyncClient) -> None:
    load_handlers()
    world = await make_world()
    member, outsider = await make_user(world.tenant), await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    task = await create_task(client, world, assignee_id=str(member.id))
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=world.headers,
        json={"body": f"{mention(member)} {mention(outsider)} {mention(world.owner)}"},
    )
    assert r.status_code == 201

    for event in await events_for(task["id"], "task.created") + await events_for(
        task["id"], "comment.created"
    ):
        await dispatch(event)
        await dispatch(event)  # redelivery must not duplicate

    tm, to = auth(await token_for(member)), auth(await token_for(outsider))
    items = (await client.get("/api/v1/notifications", headers=tm)).json()["items"]
    assert sorted(n["kind"] for n in items) == ["assigned", "mention"]
    assert (await client.get("/api/v1/notifications/unread-count", headers=tm)).json() == {"unread": 2}
    # No access to the project -> no notification (titles never leak); the actor is never notified.
    assert (await client.get("/api/v1/notifications", headers=to)).json()["items"] == []
    assert (await client.get("/api/v1/notifications", headers=world.headers)).json()["items"] == []

    r = await client.post("/api/v1/notifications/read", json={"ids": [items[0]["id"]]}, headers=tm)
    assert r.json() == {"updated": 1}
    r = await client.post("/api/v1/notifications/read", json={}, headers=tm)
    assert r.json() == {"updated": 1}
    assert (await client.get("/api/v1/notifications/unread-count", headers=tm)).json() == {"unread": 0}


async def test_stream_consumer_delivers(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    from glasshaus.core.consumers import GROUP, _ensure_group
    from glasshaus.core.events import STREAM
    from glasshaus.redis_client import get_redis

    await _ensure_group()
    await get_redis().xgroup_setid(STREAM, GROUP, "$")  # skip earlier tests' events; deliver only new ones
    stop = asyncio.Event()
    worker = asyncio.create_task(consume(stop, f"test-{uuid.uuid4().hex[:6]}", block_ms=200))
    try:
        await asyncio.sleep(0.5)  # group exists before the event is published
        await create_task(client, world, assignee_id=str(member.id))
        token = auth(await token_for(member))
        for _ in range(50):
            items = (await client.get("/api/v1/notifications", headers=token)).json()["items"]
            if items:
                break
            await asyncio.sleep(0.1)
        assert [n["kind"] for n in items] == ["assigned"]
    finally:
        stop.set()
        await asyncio.wait_for(worker, 5)


async def test_activity_feeds(client: AsyncClient) -> None:
    world, other = await make_world(), await make_world()
    task = await create_task(client, world)
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "high"}, headers=world.headers)
    await client.post(f"/api/v1/tasks/{task['id']}/comments", json={"body": "done?"}, headers=world.headers)

    feed = (await client.get("/api/v1/activity", params={"task": task["key"]}, headers=world.headers)).json()
    assert [i["type"] for i in feed["items"]] == ["comment.created", "task.updated", "task.created"]
    assert feed["items"][1]["data"]["changes"]["priority"] == {"from": "none", "to": "high"}
    project_feed = (
        await client.get(
            "/api/v1/activity", params={"project_id": str(world.project.id)}, headers=world.headers
        )
    ).json()
    assert {"project.created", "task.created", "comment.created"} <= {
        i["type"] for i in project_feed["items"]
    }
    assert "tenant_id" not in project_feed["items"][0]
    r = await client.get("/api/v1/activity", params={"task": task["id"]}, headers=other.headers)
    assert r.status_code == 404
    mine = (await client.get("/api/v1/activity", headers=other.headers)).json()["items"]
    assert all(i["project_id"] != str(world.project.id) for i in mine)
