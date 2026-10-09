"""Custom reports: definitions, the query engine, visibility, saving, sharing and export."""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus.core.rbac import OrgRole
from tests.factories import World, add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def status_id(world: World, category: str) -> str:
    return next(str(s.id) for s in world.project.statuses if s.category.value == category)


async def run(client: AsyncClient, headers: dict[str, str], **definition: Any) -> dict[str, Any]:
    r = await client.post("/api/v1/reports/run", json=definition, headers=headers)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def table(result: dict[str, Any]) -> dict[tuple[str, ...], list[float | None]]:
    return {tuple(row["labels"]): row["values"] for row in result["rows"]}


async def test_task_report_groups_measures_and_totals(client: AsyncClient) -> None:
    world = await make_world()
    today = datetime.now(UTC).date()
    late = await create_task(
        client, world, title="Late", priority="high", due_date=str(today - timedelta(days=2))
    )
    await create_task(client, world, title="Soon", priority="high", estimate_minutes=90)
    done = await create_task(
        client, world, title="Done", priority="low", due_date=str(today + timedelta(days=5))
    )
    r = await client.patch(
        f"/api/v1/tasks/{done['id']}",
        json={"status_id": status_id(world, "done"), "expected_version": done["version"]},
        headers=world.headers,
    )
    assert r.status_code == 200, r.text

    result = await run(
        client,
        world.headers,
        source="tasks",
        group_by=["priority"],
        measures=["count", "open", "done", "overdue", "estimate_hours", "on_time_pct"],
        sort={"by": "count", "descending": True},
    )
    assert [c["label"] for c in result["columns"]][:2] == ["Priority", "Tasks"]
    assert table(result) == {
        ("High",): [2, 2, 0, 1, 1.5, None],
        ("Low",): [1, 0, 1, 0, 0, 100.0],
    }
    assert result["totals"] == [3, 2, 1, 1, 1.5, 100.0]
    assert result["rows"][0]["labels"] == ["High"]  # sorted by count, descending
    assert late["key"]  # the overdue one

    two = await run(
        client, world.headers, group_by=["status_category", "priority"], measures=["count"], chart="bar"
    )
    assert table(two) == {("Done", "Low"): [1], ("To do", "High"): [2]}

    filtered = await run(
        client,
        world.headers,
        measures=["count"],
        filters={"priorities": ["high"], "date": {"field": "created", "preset": "last_7_days"}},
    )
    assert filtered["totals"] == [1 + 1] and filtered["rows"] == []
    assert filtered["date_to"] == today.isoformat()


async def test_reports_show_each_viewer_only_what_they_can_see(client: AsyncClient) -> None:
    world = await make_world()
    await create_task(client, world, title="Secret")
    outsider = auth(await token_for(await make_user(world.tenant)))
    saved = (
        await client.post(
            "/api/v1/reports",
            json={"name": "All tasks", "shared": True, "definition": {"group_by": ["project"]}},
            headers=world.headers,
        )
    ).json()
    mine = (await client.post(f"/api/v1/reports/{saved['id']}/run", headers=world.headers)).json()
    assert mine["totals"] == [1] and mine["rows"][0]["labels"] == [f"{world.project.key} Project"]
    theirs = (await client.post(f"/api/v1/reports/{saved['id']}/run", headers=outsider)).json()
    assert theirs["totals"] == [0] and theirs["rows"] == []

    member = await make_user(world.tenant)
    await add_member(client, world, member, "viewer")
    seen = (
        await client.post(f"/api/v1/reports/{saved['id']}/run", headers=auth(await token_for(member)))
    ).json()
    assert seen["totals"] == [1]


async def test_time_report_and_dashboard_overrides(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world, title="Build")
    today = datetime.now(UTC).date()
    for minutes, billable, day in (
        (60, True, today),
        (30, False, today),
        (120, True, today - timedelta(days=40)),
    ):
        r = await client.post(
            "/api/v1/time-entries",
            json={"task": task["key"], "minutes": minutes, "billable": billable, "spent_on": str(day)},
            headers=world.headers,
        )
        assert r.status_code == 201, r.text

    result = await run(
        client,
        world.headers,
        source="time",
        group_by=["person"],
        measures=["hours", "billable_hours", "entries", "people"],
        filters={"date": {"field": "spent", "preset": "last_30_days"}},
    )
    assert table(result) == {(world.owner.name,): [1.5, 1.0, 2, 1]}

    saved = (
        await client.post(
            "/api/v1/reports",
            json={"name": "Hours", "definition": {"source": "time", "measures": ["hours"]}},
            headers=world.headers,
        )
    ).json()
    everything = (await client.post(f"/api/v1/reports/{saved['id']}/run", headers=world.headers)).json()
    assert everything["totals"] == [3.5]
    recent = (
        await client.post(
            f"/api/v1/reports/{saved['id']}/run",
            json={"date": {"preset": "last_7_days"}},
            headers=world.headers,
        )
    ).json()
    assert recent["totals"] == [1.5]
    other_project = (
        await client.post(
            f"/api/v1/reports/{saved['id']}/run",
            json={"project_ids": ["00000000-0000-0000-0000-000000000000"]},
            headers=world.headers,
        )
    ).json()
    assert other_project["totals"] == [0]


async def test_custom_field_grouping(client: AsyncClient) -> None:
    world = await make_world()
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/fields",
        json={
            "name": "Team",
            "type": "select",
            "options": [{"id": "a", "label": "Apps"}, {"id": "b", "label": "Ops"}],
        },
        headers=world.headers,
    )
    team = r.json()
    points = (
        await client.post(
            f"/api/v1/projects/{world.project.id}/fields",
            json={"name": "Points", "type": "number"},
            headers=world.headers,
        )
    ).json()
    await create_task(client, world, custom_fields={team["id"]: "a"})
    await create_task(client, world, custom_fields={team["id"]: "a"})
    await create_task(client, world)
    result = await run(client, world.headers, group_by=[f"cf:{team['id']}"])
    assert result["columns"][0]["label"] == "Team"
    assert table(result) == {("Apps",): [2], ("(none)",): [1]}
    r = await client.post(
        "/api/v1/reports/run", json={"group_by": [f"cf:{points['id']}"]}, headers=world.headers
    )
    assert r.status_code == 422 and "single-select" in r.text
    outsider = auth(await token_for(await make_user(world.tenant)))
    r = await client.post("/api/v1/reports/run", json={"group_by": [f"cf:{team['id']}"]}, headers=outsider)
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("definition", "message"),
    [
        ({"source": "time", "measures": ["count"]}, "not a measure for time"),
        ({"group_by": ["person"]}, "not a grouping for tasks"),
        ({"group_by": ["priority", "priority"]}, "used once"),
        ({"measures": ["count"], "sort": {"by": "hours"}}, "sort by"),
        ({"filters": {"date": {"preset": "custom"}}}, "date_from and date_to"),
        ({"source": "time", "filters": {"priorities": ["high"]}}, "apply to task reports"),
        ({"group_by": ["cf:not-a-uuid"]}, "custom field"),
        ({"group_by": ["priority", "status", "project"]}, "at most 2"),
        ({"limit": 501}, "less than or equal"),
    ],
)
async def test_definitions_are_validated(
    client: AsyncClient, definition: dict[str, Any], message: str
) -> None:
    world = await make_world()
    r = await client.post("/api/v1/reports/run", json=definition, headers=world.headers)
    assert r.status_code == 422 and message in r.text, r.text


async def test_saving_sharing_and_export(client: AsyncClient) -> None:
    world = await make_world()
    await create_task(client, world, tags=["=HYPERLINK(1)", "ok"])
    member = await make_user(world.tenant)
    mt = auth(await token_for(member))
    body = {"name": "By tag", "definition": {"group_by": ["tag"], "measures": ["count"]}}
    mine = (await client.post("/api/v1/reports", json=body, headers=mt)).json()
    assert (await client.get("/api/v1/reports", headers=world.headers)).json() == []  # private by default
    r = await client.patch(f"/api/v1/reports/{mine['id']}", json={"shared": True}, headers=mt)
    assert r.json()["shared"] is True
    assert [x["id"] for x in (await client.get("/api/v1/reports", headers=world.headers)).json()] == [
        mine["id"]
    ]
    other = auth(await token_for(await make_user(world.tenant)))
    assert (
        await client.patch(f"/api/v1/reports/{mine['id']}", json={"name": "x"}, headers=other)
    ).status_code == 403

    saved = (
        await client.post("/api/v1/reports", json={**body, "name": "Tags (owner)"}, headers=world.headers)
    ).json()
    r = await client.get(f"/api/v1/reports/{saved['id']}/export", headers=world.headers)
    assert r.status_code == 200 and "glasshaus-Tags-owner.csv" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["Tag", "Tasks"]
    assert ["'=hyperlink(1)", "1.0"] in rows and ["Total", "1.0"] in rows  # formula neutralised

    guest = await make_user(world.tenant, OrgRole.GUEST)
    r = await client.post(
        "/api/v1/reports", json={**body, "shared": True}, headers=auth(await token_for(guest))
    )
    assert r.status_code == 403
    assert (await client.delete(f"/api/v1/reports/{mine['id']}", headers=world.headers)).status_code == 204
    assert (await client.get(f"/api/v1/reports/{mine['id']}", headers=mt)).status_code == 404


async def test_dashboard_report_tile(client: AsyncClient) -> None:
    world = await make_world()
    saved = (
        await client.post(
            "/api/v1/reports", json={"name": "Open", "definition": {"chart": "kpi"}}, headers=world.headers
        )
    ).json()
    body = {
        "name": "KPIs",
        "widgets": [
            {"id": "k", "type": "report", "config": {"report_id": saved["id"], "target": 5, "good": "down"}}
        ],
    }
    r = await client.post("/api/v1/dashboards", json=body, headers=world.headers)
    assert r.status_code == 201 and r.json()["widgets"][0]["type"] == "report"
