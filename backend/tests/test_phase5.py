"""Time tracking, workload, reports, dashboards, portfolios and OKRs."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from tests.factories import World, add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def today() -> date:
    return datetime.now(UTC).date()


def status_id(world: World, category: str) -> str:
    return next(str(s.id) for s in world.project.statuses if s.category.value == category)


async def log(
    client: AsyncClient, headers: dict[str, str], task: str, minutes: int, **extra: Any
) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/time-entries", json={"task": task, "minutes": minutes, **extra}, headers=headers
    )
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


# --------------------------------------------------------------------------- time tracking


async def test_time_entries_permissions_and_visibility(client: AsyncClient) -> None:
    world = await make_world()
    editor, viewer, outsider = [await make_user(world.tenant) for _ in range(3)]
    await add_member(client, world, editor, "editor")
    await add_member(client, world, viewer, "viewer")
    te, tv, to = [auth(await token_for(u)) for u in (editor, viewer, outsider)]
    task = await create_task(client, world)

    mine = await log(client, te, task["key"], 90, note="pairing", billable=True)
    assert mine["task_key"] == task["key"] and mine["spent_on"] == str(today())
    r = await client.post("/api/v1/time-entries", json={"task": task["key"], "minutes": 30}, headers=tv)
    assert r.status_code == 403  # viewers cannot log time
    future = str(today() + timedelta(days=5))
    r = await client.post(
        "/api/v1/time-entries", json={"task": task["key"], "minutes": 5, "spent_on": future}, headers=te
    )
    assert r.status_code == 422

    # Project readers see the entry; outsiders do not.
    assert (
        len(
            (await client.get("/api/v1/time-entries", params={"task": task["key"]}, headers=tv)).json()[
                "items"
            ]
        )
        == 1
    )
    assert (await client.get("/api/v1/time-entries", headers=to)).json()["items"] == []
    # Only the author or a project admin edits.
    url = f"/api/v1/time-entries/{mine['id']}"
    assert (await client.patch(url, json={"minutes": 10}, headers=tv)).status_code == 403
    assert (await client.patch(url, json={"minutes": 45}, headers=te)).json()["minutes"] == 45
    assert (await client.patch(url, json={"note": "admin fix"}, headers=world.headers)).status_code == 200
    assert (await client.delete(url, headers=to)).status_code == 404
    assert (await client.delete(url, headers=te)).status_code == 204


async def test_timer_logs_time_once(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world)
    assert (await client.get("/api/v1/timer", headers=world.headers)).json() is None
    started = await client.post(
        "/api/v1/timer", json={"task": task["key"], "note": "deep work"}, headers=world.headers
    )
    assert started.status_code == 201 and started.json()["task_key"] == task["key"]
    again = await client.post("/api/v1/timer", json={"task": task["key"]}, headers=world.headers)
    assert again.status_code == 409
    entry = (await client.post("/api/v1/timer/stop", json={"billable": True}, headers=world.headers)).json()
    assert (
        entry["minutes"] == 1 and entry["note"] == "deep work" and entry["billable"] and entry["started_at"]
    )
    assert (await client.post("/api/v1/timer/stop", json={}, headers=world.headers)).status_code == 404


async def test_timesheet_report_and_csv(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    tm = auth(await token_for(member))
    a = await create_task(client, world, title='=HYPERLINK("http://evil")')
    b = await create_task(client, world, title="Write docs")
    yesterday = str(today() - timedelta(days=1))
    await log(client, tm, a["key"], 60, spent_on=yesterday, billable=True)
    await log(client, tm, a["key"], 30)
    await log(client, tm, b["key"], 15)
    await log(client, world.headers, b["key"], 120)

    sheet = (await client.get("/api/v1/timesheets", headers=tm)).json()
    assert sheet["total"] == 105 and sheet["billable_total"] == 60 and len(sheet["days"]) == 7
    row = next(r for r in sheet["rows"] if r["task_key"] == a["key"])
    assert row["minutes_by_day"] == {yesterday: 60, str(today()): 30}
    # An admin pulls someone else's timesheet: who put time towards which projects.
    other = (
        await client.get("/api/v1/timesheets", params={"user_id": str(member.id)}, headers=world.headers)
    ).json()
    assert other["total"] == 105
    report = (await client.get("/api/v1/reports/time", headers=world.headers)).json()
    by_user = {r["user_id"]: r["minutes"] for r in report["rows"]}
    assert by_user == {str(member.id): 105, str(world.owner.id): 120} and report["total"] == 225

    r = await client.get(
        "/api/v1/time-entries/export", params={"project_id": str(world.project.id)}, headers=world.headers
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4 and sum(int(x["minutes"]) for x in rows) == 225
    assert all(not x["title"].startswith("=") for x in rows)  # formulas neutralized


# --------------------------------------------------------------------------- workload and reports


async def test_workload_spreads_remaining_work(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    r = await client.patch(
        f"/api/v1/users/{member.id}", json={"capacity_minutes": 360}, headers=world.headers
    )
    assert r.json()["capacity_minutes"] == 360 and r.json()["working_days"] == [0, 1, 2, 3, 4]
    monday = today() - timedelta(days=today().weekday()) + timedelta(days=7)
    task = await create_task(
        client,
        world,
        assignee_id=str(member.id),
        estimate_minutes=600,
        start_date=str(monday),
        due_date=str(monday + timedelta(days=4)),
    )
    await create_task(client, world, assignee_id=str(member.id))  # no estimate
    await create_task(client, world, assignee_id=str(member.id), estimate_minutes=120)  # no dates
    await log(client, auth(await token_for(member)), task["key"], 100)

    params = {
        "project_id": str(world.project.id),
        "date_from": str(monday),
        "date_to": str(monday + timedelta(days=13)),
    }
    data = (await client.get("/api/v1/workload", params=params, headers=world.headers)).json()
    person = next(u for u in data["users"] if u["user_id"] == str(member.id))
    assert [b["planned"] for b in person["buckets"]] == [500, 0]
    assert [b["capacity"] for b in person["buckets"]] == [1800, 1800]
    assert (
        person["unestimated_tasks"] == 1
        and person["unscheduled_minutes"] == 120
        and person["open_tasks"] == 3
    )
    daily = (
        await client.get("/api/v1/workload", params={**params, "bucket": "day"}, headers=world.headers)
    ).json()
    assert len(daily["buckets"]) == 14


async def test_project_report_health_and_export(client: AsyncClient) -> None:
    world = await make_world()
    done = status_id(world, "done")
    finished = await create_task(client, world, estimate_minutes=60, priority="high")
    await client.patch(f"/api/v1/tasks/{finished['id']}", json={"status_id": done}, headers=world.headers)
    await log(client, world.headers, finished["key"], 75)
    await create_task(client, world, due_date=str(today() - timedelta(days=2)), tags=["ops"])
    await create_task(client, world, custom_fields={})

    report = (await client.get(f"/api/v1/projects/{world.project.id}/report", headers=world.headers)).json()
    assert (report["total"], report["open"], report["done"], report["overdue"]) == (3, 2, 1, 1)
    assert report["burnup"][-1] == {"day": str(today()), "scope": 3, "done": 1}
    assert sum(p["completed"] for p in report["throughput"]) == 1
    assert (
        report["estimate_minutes"] == 60 and report["actual_minutes"] == 75 and report["logged_minutes"] == 75
    )
    assert report["lead_time_days"]["median"] is not None
    health = (await client.get(f"/api/v1/projects/{world.project.id}/health", headers=world.headers)).json()
    assert health["progress"] == pytest.approx(1 / 3, abs=0.001) and health["health"] == "off_track"

    r = await client.get(f"/api/v1/projects/{world.project.id}/tasks/export", headers=world.headers)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [x["key"] for x in rows] == [f"{world.project.key}-{n}" for n in (1, 2, 3)]
    assert rows[0]["logged_minutes"] == "75" and rows[1]["tags"] == "ops"
    outsider = await make_world()
    assert (
        await client.get(f"/api/v1/projects/{world.project.id}/report", headers=outsider.headers)
    ).status_code == 404


# --------------------------------------------------------------------------- dashboards, portfolios, OKRs


async def test_dashboards(client: AsyncClient) -> None:
    world = await make_world()
    member, guest_user = await make_user(world.tenant), await make_user(world.tenant)
    tm = auth(await token_for(member))
    body = {
        "name": "Ops",
        "widgets": [
            {"id": "a", "type": "my_tasks"},
            {"id": "b", "type": "burnup", "width": 2, "config": {"project_id": str(world.project.id)}},
        ],
    }
    mine = (await client.post("/api/v1/dashboards", json=body, headers=tm)).json()
    assert [w["type"] for w in mine["widgets"]] == ["my_tasks", "burnup"]
    assert (await client.get("/api/v1/dashboards", headers=world.headers)).json() == []  # private by default
    dup = {**body, "widgets": [{"id": "a", "type": "my_tasks"}, {"id": "a", "type": "workload"}]}
    assert (await client.post("/api/v1/dashboards", json=dup, headers=tm)).status_code == 422
    await client.patch(f"/api/v1/dashboards/{mine['id']}", json={"shared": True}, headers=tm)
    assert [d["id"] for d in (await client.get("/api/v1/dashboards", headers=world.headers)).json()] == [
        mine["id"]
    ]
    other = auth(await token_for(guest_user))
    assert (
        await client.patch(f"/api/v1/dashboards/{mine['id']}", json={"name": "x"}, headers=other)
    ).status_code == 403
    assert (await client.delete(f"/api/v1/dashboards/{mine['id']}", headers=world.headers)).status_code == 204


async def test_portfolio_rolls_up_visible_projects(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    tm = auth(await token_for(member))
    r = await client.post(
        "/api/v1/projects",
        json={
            "workspace_id": str(world.workspace_id),
            "key": "P" + uuid.uuid4().hex[:4].upper(),
            "name": "Second",
        },
        headers=world.headers,
    )
    second = r.json()
    await add_member(client, world, member, "viewer")  # member sees only the first project
    t = await create_task(client, world)
    await client.patch(
        f"/api/v1/tasks/{t['id']}", json={"status_id": status_id(world, "done")}, headers=world.headers
    )
    await create_task(client, world)

    body = {"name": "Q4 launches", "project_ids": [str(world.project.id), second["id"]]}
    portfolio = (await client.post("/api/v1/portfolios", json=body, headers=world.headers)).json()
    assert portfolio["project_count"] == 2 and portfolio["progress"] == 0.5
    seen = (await client.get(f"/api/v1/portfolios/{portfolio['id']}", headers=tm)).json()
    assert [p["key"] for p in seen["projects"]] == [world.project.key]
    assert (
        await client.patch(f"/api/v1/portfolios/{portfolio['id']}", json={"name": "x"}, headers=tm)
    ).status_code == 403
    bad = {"project_ids": [str(uuid.uuid4())]}
    assert (
        await client.patch(f"/api/v1/portfolios/{portfolio['id']}", json=bad, headers=world.headers)
    ).status_code == 404


async def test_okrs_progress_and_check_ins(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    tm = auth(await token_for(member))
    done = status_id(world, "done")
    for i in range(4):
        t = await create_task(client, world, tags=["launch"] if i < 2 else [])
        if i == 0:
            await client.patch(f"/api/v1/tasks/{t['id']}", json={"status_id": done}, headers=world.headers)
    body = {
        "title": "Ship the relaunch",
        "period": "2026-Q4",
        "key_results": [
            {"title": "Signups", "kind": "metric", "start_value": 100, "target_value": 300, "unit": "users"},
            {
                "title": "Launch tasks done",
                "kind": "tasks",
                "project_id": str(world.project.id),
                "tag": "launch",
            },
        ],
    }
    objective = (await client.post("/api/v1/objectives", json=body, headers=world.headers)).json()
    metric, tasks = objective["key_results"]
    assert metric["progress"] == 0 and tasks["progress"] == 0.5 and tasks["total_tasks"] == 2
    assert objective["progress"] == 0.25

    r = await client.post(
        f"/api/v1/key-results/{metric['id']}/check-ins",
        json={"value": 250, "confidence": "at_risk"},
        headers=world.headers,
    )
    assert r.status_code == 201
    bad = await client.post(
        f"/api/v1/key-results/{tasks['id']}/check-ins",
        json={"value": 3, "confidence": "on_track"},
        headers=world.headers,
    )
    assert bad.status_code == 422
    updated = (await client.get(f"/api/v1/objectives/{objective['id']}", headers=world.headers)).json()
    assert updated["key_results"][0]["progress"] == 0.75 and updated["progress"] == 0.625
    assert updated["confidence"] == "at_risk"
    # Someone who cannot read the project sees the objective, not the project's progress.
    hidden = (await client.get(f"/api/v1/objectives/{objective['id']}", headers=tm)).json()
    assert hidden["key_results"][1]["progress"] is None and hidden["progress"] == 0.75
    assert (
        await client.patch(f"/api/v1/objectives/{objective['id']}", json={"title": "x"}, headers=tm)
    ).status_code == 403
    child = (
        await client.post(
            "/api/v1/objectives",
            json={"title": "Child", "period": "2026-Q4", "parent_id": objective["id"]},
            headers=tm,
        )
    ).json()
    cycle = await client.patch(
        f"/api/v1/objectives/{objective['id']}", json={"parent_id": child["id"]}, headers=world.headers
    )
    assert cycle.status_code == 422
    assert [
        o["id"]
        for o in (await client.get("/api/v1/objectives", params={"period": "2026-Q4"}, headers=tm)).json()
    ] == [
        objective["id"],
        child["id"],
    ]
    history = (await client.get(f"/api/v1/key-results/{metric['id']}/check-ins", headers=tm)).json()
    assert [h["value"] for h in history] == [250]
