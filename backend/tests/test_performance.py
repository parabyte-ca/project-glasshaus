"""Query counts stay flat as data grows: no per-project or per-task round-trips on list pages."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from glasshaus.core.rbac import OrgRole
from glasshaus.db import get_engine, unit_of_work
from glasshaus.projects import service as projects
from glasshaus.projects.schemas import ProjectCreate
from tests.factories import World, actor_for, auth, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


@contextmanager
def queries() -> Iterator[list[str]]:
    seen: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if not statement.lstrip().upper().startswith(("SELECT SET_CONFIG", "BEGIN", "COMMIT", "ROLLBACK")):
            seen.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", count)


async def more_projects(world: World, n: int) -> list[uuid.UUID]:
    ids = []
    async with unit_of_work(actor_for(world.owner)) as ctx:
        for _ in range(n):
            p = await projects.create_project(
                ctx,
                ProjectCreate(
                    workspace_id=world.workspace_id, key="Q" + uuid.uuid4().hex[:6].upper(), name="Q"
                ),
            )
            ids.append(p.id)
    return ids


async def member_of(client: AsyncClient, world: World, project_ids: list[uuid.UUID]) -> dict[str, str]:
    member = await make_user(world.tenant, OrgRole.MEMBER)
    for pid in project_ids:
        r = await client.put(
            f"/api/v1/projects/{pid}/members",
            json={"user_id": str(member.id), "role": "editor"},
            headers=world.headers,
        )
        assert r.status_code == 200, r.text
    return auth(await token_for(member))


async def count(client: AsyncClient, path: str, headers: dict[str, str]) -> int:
    with queries() as seen:
        r = await client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    return len(seen)


async def test_project_list_does_not_grow_with_projects(client: AsyncClient) -> None:
    small, large = await make_world(), await make_world()
    few = await member_of(client, small, [small.project.id, *await more_projects(small, 2)])
    many = await member_of(client, large, [large.project.id, *await more_projects(large, 20)])
    assert len((await client.get("/api/v1/projects", headers=many)).json()) == 21
    await client.get("/api/v1/projects", headers=few)  # first use of a token records last_used_at
    assert await count(client, "/api/v1/projects", many) == await count(client, "/api/v1/projects", few)


async def test_portfolio_and_okrs_do_not_grow_with_projects(client: AsyncClient) -> None:
    results = []
    for n in (2, 12):
        world = await make_world()
        ids = [world.project.id, *await more_projects(world, n - 1)]
        for pid in ids:
            r = await client.post(
                "/api/v1/tasks", json={"project_id": str(pid), "title": "t"}, headers=world.headers
            )
            assert r.status_code == 201
        headers = await member_of(client, world, ids)
        r = await client.post("/api/v1/portfolios", json={"name": "All", "project_ids": [str(i) for i in ids]},
                              headers=world.headers)  # fmt: skip
        assert r.status_code == 201, r.text
        portfolio = r.json()["id"]
        r = await client.post(
            "/api/v1/objectives",
            json={"title": "Ship", "period": "2026-Q4",
                  "key_results": [{"title": f"P{i}", "kind": "tasks", "project_id": str(p)} for i, p in enumerate(ids[:10])]},
            headers=world.headers,
        )  # fmt: skip
        assert r.status_code == 201, r.text
        detail = (await client.get(f"/api/v1/portfolios/{portfolio}", headers=headers)).json()
        assert len(detail["projects"]) == n and all(p["total"] == 1 for p in detail["projects"])
        okrs = (await client.get("/api/v1/objectives", headers=headers)).json()
        assert all(kr["total_tasks"] == 1 for kr in okrs[0]["key_results"])
        results.append(
            (
                await count(client, f"/api/v1/portfolios/{portfolio}", headers),
                await count(client, "/api/v1/objectives", headers),
            )
        )
    assert results[0] == results[1], results


async def test_workload_does_not_grow_with_tasks(client: AsyncClient) -> None:
    results = []
    for n in (2, 30):
        world = await make_world()
        for i in range(n):
            r = await client.post(
                "/api/v1/tasks",
                json={"project_id": str(world.project.id), "title": f"t{i}", "assignee_id": str(world.owner.id),
                      "estimate_minutes": 60, "due_date": "2030-01-10"},
                headers=world.headers,
            )  # fmt: skip
            assert r.status_code == 201, r.text
        body = (await client.get("/api/v1/workload", headers=world.headers)).json()
        assert body["users"][0]["open_tasks"] == n
        results.append(await count(client, "/api/v1/workload", world.headers))
    assert results[0] == results[1], results


async def test_bulk_date_change_reschedules_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from glasshaus.scheduling import service as scheduling

    world = await make_world()
    r = await client.patch(
        f"/api/v1/projects/{world.project.id}", json={"auto_schedule": True}, headers=world.headers
    )
    assert r.status_code == 200, r.text
    ids = []
    for i in range(5):
        r = await client.post(
            "/api/v1/tasks",
            json={"project_id": str(world.project.id), "title": f"t{i}", "start_date": "2030-01-01", "due_date": "2030-01-02"},
            headers=world.headers,
        )  # fmt: skip
        ids.append(r.json()["id"])
    calls: list[set[uuid.UUID]] = []
    real = scheduling.propagate_from

    async def spy(ctx: Any, project: Any, task_ids: set[uuid.UUID]) -> Any:
        calls.append(set(task_ids))
        return await real(ctx, project, task_ids)

    monkeypatch.setattr(scheduling, "propagate_from", spy)
    r = await client.post(
        "/api/v1/tasks/bulk-update",
        json={"task_ids": ids, "patch": {"due_date": "2030-01-05"}},
        headers=world.headers,
    )
    assert r.status_code == 200 and len(r.json()["updated"]) == 5, r.text
    assert calls == [{uuid.UUID(i) for i in ids}]
