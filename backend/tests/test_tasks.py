from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus.core.events import STREAM
from glasshaus.redis_client import get_redis
from tests.factories import create_task, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def _status(world, category: str) -> str:  # type: ignore[no-untyped-def]
    return next(str(s.id) for s in world.project.statuses if s.category == category)


async def test_create_numbering_and_defaults(client: AsyncClient) -> None:
    world = await make_world(key="NUM")
    first = await create_task(client, world, tags=["Backend", "backend ", "API"])
    second = await create_task(client, world)
    assert (first["key"], second["key"]) == ("NUM-1", "NUM-2")
    assert first["status"]["category"] == "todo"
    assert first["tags"] == ["api", "backend"]
    assert second["position"] > first["position"]
    got = await client.get("/api/v1/tasks/num-2", headers=world.headers)
    assert got.json()["id"] == second["id"] and got.headers["etag"] == 'W/"1"'


async def test_update_status_concurrency_and_validation(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world)
    url = f"/api/v1/tasks/{task['id']}"
    r = await client.patch(url, json={"status_id": _status(world, "done")}, headers=world.headers)
    assert r.status_code == 200 and r.json()["completed_at"] is not None and r.json()["version"] == 2
    r = await client.patch(url, json={"title": "stale"}, headers={**world.headers, "If-Match": 'W/"1"'})
    assert r.status_code == 412 and r.json()["current_version"] == 2
    r = await client.patch(url, json={"status_id": _status(world, "todo")}, headers=world.headers)
    assert r.json()["completed_at"] is None
    r = await client.patch(
        url, json={"start_date": "2026-05-10", "due_date": "2026-05-01"}, headers=world.headers
    )
    assert r.status_code == 422
    child = await create_task(client, world, parent_id=task["id"])
    r = await client.patch(url, json={"parent_id": child["id"]}, headers=world.headers)
    assert r.status_code == 422 and "ancestor" in r.json()["detail"]


async def test_filters_sorting_and_pagination(client: AsyncClient) -> None:
    world = await make_world(key="FLT")
    for i in range(7):
        await create_task(
            client,
            world,
            title=f"Item {i}",
            priority=["low", "high"][i % 2],
            tags=["odd"] if i % 2 else [],
            due_date=f"2026-01-{10 + i:02d}",
        )
    params: dict[str, Any] = {
        "project_id": str(world.project.id),
        "limit": 3,
        "sort": "due_date",
        "descending": True,
    }
    page1 = (await client.get("/api/v1/tasks", params=params, headers=world.headers)).json()
    assert [t["title"] for t in page1["items"]] == ["Item 6", "Item 5", "Item 4"]
    page2 = (
        await client.get(
            "/api/v1/tasks", params={**params, "cursor": page1["next_cursor"]}, headers=world.headers
        )
    ).json()
    assert [t["title"] for t in page2["items"]] == ["Item 3", "Item 2", "Item 1"]

    async def n(**kw: Any) -> int:
        r = await client.get(
            "/api/v1/tasks", params={"project_id": str(world.project.id), **kw}, headers=world.headers
        )
        assert r.status_code == 200, r.text
        return len(r.json()["items"])

    assert await n(priorities=["high"]) == 3
    assert await n(tags=["odd"]) == 3
    assert await n(q="FLT-2") == 1
    assert await n(q="item") == 7
    assert await n(due_before="2026-01-12") == 3
    assert await n(status_categories=["done"]) == 0
    assert (
        await client.get("/api/v1/tasks", params={"cursor": "garbage"}, headers=world.headers)
    ).status_code == 422


async def test_bulk_update_across_projects(client: AsyncClient) -> None:
    world = await make_world()
    tasks = [await create_task(client, world) for _ in range(3)]
    r = await client.post(
        "/api/v1/tasks/bulk-update",
        headers=world.headers,
        json={
            "task_ids": [t["id"] for t in tasks] + ["00000000-0000-0000-0000-000000000000"],
            "patch": {"status_category": "in_progress", "priority": "urgent", "add_tags": ["Sprint-1"]},
        },
    )
    body = r.json()
    assert len(body["updated"]) == 3 and list(body["failed"].values()) == ["task not found"]
    got = (await client.get(f"/api/v1/tasks/{tasks[0]['id']}", headers=world.headers)).json()
    assert (got["status"]["category"], got["priority"], got["tags"]) == (
        "in_progress",
        "urgent",
        ["sprint-1"],
    )


async def test_delete_dry_run_then_restore(client: AsyncClient) -> None:
    world = await make_world()
    parent = await create_task(client, world)
    child = await create_task(client, world, parent_id=parent["id"])
    await create_task(client, world, parent_id=child["id"])
    preview = (
        await client.post(
            "/api/v1/tasks/bulk-delete", json={"task_ids": [parent["id"]]}, headers=world.headers
        )
    ).json()
    assert preview == [
        {"resource": "task", "id": parent["id"], "executed": False, "affected": {"subtasks": 2}}
    ]
    assert (await client.get(f"/api/v1/tasks/{child['id']}", headers=world.headers)).json()[
        "deleted_at"
    ] is None
    assert (await client.delete(f"/api/v1/tasks/{parent['id']}", headers=world.headers)).status_code == 204
    listed = (
        await client.get("/api/v1/tasks", params={"project_id": str(world.project.id)}, headers=world.headers)
    ).json()["items"]
    assert listed == []
    r = await client.post(f"/api/v1/tasks/{parent['id']}/restore", headers=world.headers)
    assert r.status_code == 200 and r.json()["deleted_at"] is None


async def test_events_are_relayed_to_stream(client: AsyncClient) -> None:
    world = await make_world()
    redis = get_redis()
    last = await redis.xrevrange(STREAM, count=1)
    start = last[0][0] if last else "0"
    task = await create_task(client, world, title="evented")
    entries = await redis.xrange(STREAM, min=f"({start}")
    bodies = [e[1]["event"] for e in entries]
    assert any('"task.created"' in b and task["id"] in b for b in bodies)


async def test_statuses_and_project_lifecycle(client: AsyncClient) -> None:
    world = await make_world()
    pid = world.project.id
    task = await create_task(client, world)
    todo = task["status"]["id"]
    r = await client.post(
        f"/api/v1/projects/{pid}/statuses",
        json={"name": "Review", "category": "in_progress"},
        headers=world.headers,
    )
    review = r.json()["id"]
    assert r.status_code == 201
    assert (
        await client.delete(f"/api/v1/projects/{pid}/statuses/{todo}", headers=world.headers)
    ).status_code == 422
    r = await client.delete(
        f"/api/v1/projects/{pid}/statuses/{todo}",
        params={"replacement_status_id": review},
        headers=world.headers,
    )
    assert r.status_code == 204
    moved = (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()
    assert moved["status"]["name"] == "Review"
    dup = {"workspace_id": str(world.workspace_id), "key": world.project.key, "name": "dup"}
    assert (await client.post("/api/v1/projects", json=dup, headers=world.headers)).status_code == 409
    preview = (await client.delete(f"/api/v1/projects/{pid}", headers=world.headers)).json()
    assert preview["executed"] is False and preview["affected"]["tasks"] == 1
    r = await client.delete(f"/api/v1/projects/{pid}", params={"dry_run": False}, headers=world.headers)
    assert r.json()["executed"] is True
    assert (await client.get(f"/api/v1/projects/{pid}", headers=world.headers)).status_code == 404
