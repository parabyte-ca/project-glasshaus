from datetime import date

import pytest
from httpx import AsyncClient

from tests.factories import add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def link(client: AsyncClient, world, pred: dict, succ: dict, **extra: object):  # type: ignore[no-untyped-def,type-arg]
    return await client.post(
        "/api/v1/dependencies",
        headers=world.headers,
        json={"predecessor": pred["key"], "successor": succ["key"], **extra},
    )


async def test_dependency_rules(client: AsyncClient) -> None:
    world, other = await make_world(), await make_world()
    a, b, c = [await create_task(client, world, title=t) for t in "ABC"]
    assert (await link(client, world, a, b)).status_code == 201
    assert (await link(client, world, b, c)).status_code == 201
    r = await link(client, world, c, a)
    assert r.status_code == 422 and "cycle" in r.json()["detail"]
    assert (await link(client, world, a, b)).status_code == 409
    assert (await link(client, world, a, a)).status_code == 422
    foreign = await create_task(client, other)
    r = await client.post(
        "/api/v1/dependencies",
        headers=world.headers,
        json={"predecessor": a["key"], "successor": foreign["id"]},
    )
    assert r.status_code == 404  # other tenant's task is invisible
    deps = (await client.get(f"/api/v1/tasks/{b['key']}/dependencies", headers=world.headers)).json()
    assert [d["predecessor_key"] for d in deps["predecessors"]] == [a["key"]]
    assert [d["successor_key"] for d in deps["successors"]] == [c["key"]]

    viewer = await make_user(world.tenant)
    await add_member(client, world, viewer, "viewer")
    r = await client.post(
        "/api/v1/dependencies",
        headers=auth(await token_for(viewer)),
        json={"predecessor": b["key"], "successor": a["key"]},
    )
    assert r.status_code == 403


async def test_auto_schedule_and_manual_reschedule(client: AsyncClient) -> None:
    world = await make_world()
    a = await create_task(client, world, title="Design", start_date="2026-03-02", due_date="2026-03-04")
    b = await create_task(client, world, title="Build", start_date="2026-03-03", due_date="2026-03-06")
    c = await create_task(client, world, title="Ship", start_date="2026-03-09", due_date="2026-03-09")

    # Auto-schedule off: the link is stored, B is flagged, nothing moves.
    r = await link(client, world, a, b)
    assert r.json()["rescheduled"] == []
    warnings = (
        await client.get(
            f"/api/v1/projects/{world.project.id}/schedule/warnings",
            params={"today": "2026-03-01"},
            headers=world.headers,
        )
    ).json()
    assert [(w["kind"], w["key"], w["days"]) for w in warnings] == [("dependency_violated", b["key"], 2)]

    preview = (
        await client.post(f"/api/v1/projects/{world.project.id}/reschedule", headers=world.headers)
    ).json()
    assert preview["executed"] is False
    assert [(m["key"], m["new_start_date"], m["new_due_date"]) for m in preview["moves"]] == [
        (b["key"], "2026-03-05", "2026-03-08")
    ]
    assert (await client.get(f"/api/v1/tasks/{b['id']}", headers=world.headers)).json()[
        "start_date"
    ] == "2026-03-03"
    await client.post(
        f"/api/v1/projects/{world.project.id}/reschedule", params={"dry_run": False}, headers=world.headers
    )
    assert (await client.get(f"/api/v1/tasks/{b['id']}", headers=world.headers)).json()[
        "start_date"
    ] == "2026-03-05"

    # Auto-schedule on: linking and date changes cascade.
    await client.patch(
        f"/api/v1/projects/{world.project.id}", json={"auto_schedule": True}, headers=world.headers
    )
    r = await link(client, world, b, c, lag_days=1)
    assert [m["key"] for m in r.json()["rescheduled"]] == [c["key"]]  # C must wait until the 10th
    await client.patch(f"/api/v1/tasks/{a['id']}", json={"due_date": "2026-03-10"}, headers=world.headers)
    got = {
        t["key"]: (t["start_date"], t["due_date"])
        for t in (
            await client.get(
                "/api/v1/tasks", params={"project_id": str(world.project.id)}, headers=world.headers
            )
        ).json()["items"]
    }
    assert got[b["key"]] == ("2026-03-11", "2026-03-14")
    assert got[c["key"]] == ("2026-03-16", "2026-03-16")
    feed = (await client.get("/api/v1/activity", params={"task": c["key"]}, headers=world.headers)).json()[
        "items"
    ]
    assert feed[0]["data"]["reason"] == "auto_schedule"


async def test_critical_path_baselines_and_calendar(client: AsyncClient) -> None:
    world = await make_world()
    a = await create_task(client, world, title="A", start_date="2026-04-01", due_date="2026-04-03")
    b = await create_task(client, world, title="B", start_date="2026-04-04", due_date="2026-04-10")
    side = await create_task(client, world, title="Side", start_date="2026-04-04", due_date="2026-04-05")
    floating = await create_task(client, world, title="No dates")
    await link(client, world, a, b)
    await link(client, world, a, side)
    sched = (await client.get(f"/api/v1/projects/{world.project.id}/schedule", headers=world.headers)).json()
    assert sched["project_finish"] == "2026-04-10"
    rows = {t["key"]: t for t in sched["tasks"]}
    assert rows[a["key"]]["critical"] and rows[b["key"]]["critical"]
    assert rows[side["key"]]["slack_days"] == 5 and not rows[side["key"]]["critical"]
    assert sched["unscheduled"] == [floating["id"]]
    assert len(sched["dependencies"]) == 2

    base = (
        await client.post(
            f"/api/v1/projects/{world.project.id}/baselines", json={"name": "Plan v1"}, headers=world.headers
        )
    ).json()
    assert base["task_count"] == 4
    await client.patch(f"/api/v1/tasks/{b['id']}", json={"due_date": "2026-04-13"}, headers=world.headers)
    variance = (await client.get(f"/api/v1/baselines/{base['id']}/variance", headers=world.headers)).json()
    assert variance["finish_variance_days"] == 3
    assert {t["key"]: t["finish_variance_days"] for t in variance["tasks"]}[b["key"]] == 3
    kinds = {
        w["kind"]
        for w in (
            await client.get(
                f"/api/v1/projects/{world.project.id}/schedule/warnings",
                params={"today": "2026-04-06"},
                headers=world.headers,
            )
        ).json()
    }
    assert {"behind_baseline", "finish_behind_baseline", "overdue"} <= kinds  # A and Side are overdue

    window = {
        "project_id": str(world.project.id),
        "scheduled_from": "2026-04-05",
        "scheduled_to": "2026-04-07",
    }
    keys = {
        t["key"]
        for t in (await client.get("/api/v1/tasks", params=window, headers=world.headers)).json()["items"]
    }
    assert keys == {b["key"], side["key"]}
    assert (await client.delete(f"/api/v1/baselines/{base['id']}", headers=world.headers)).status_code == 204
    assert date.fromisoformat(sched["project_start"]) == date(2026, 4, 1)
