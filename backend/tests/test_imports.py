from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus.core.rbac import OrgRole
from glasshaus.imports.service import RowError, parse_date, parse_estimate
from tests.factories import add_member, auth, events_for, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

ALL = [
    "external_id",
    "title",
    "description",
    "status",
    "priority",
    "assignee",
    "due_date",
    "tags",
    "parent",
    "links",
]


async def _import(client: AsyncClient, world, rows: list[dict[str, Any]], **body: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    payload = {"source": "nimble", "fields": ALL, "rows": rows, **body}
    r = await client.post(f"/api/v1/projects/{world.project.id}/import", json=payload, headers=world.headers)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


async def _tasks(client: AsyncClient, world) -> dict[str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = await client.get(
        "/api/v1/tasks", params={"project_id": str(world.project.id), "limit": 200}, headers=world.headers
    )
    assert r.status_code == 200, r.text
    return {t["title"]: t for t in r.json()["items"]}


def _row(n: int, **cells: Any) -> dict[str, Any]:
    return {"row": n + 1, "external_id": f"W-{n}", "title": f"Item {n}", **cells}


async def test_import_creates_matches_people_and_updates_in_place(client: AsyncClient) -> None:
    world = await make_world()
    pat = await make_user(world.tenant, email="pat@example.com")
    await add_member(client, world, pat, "editor")
    await make_user(world.tenant, email="outsider@example.com")  # in the org, not in the project
    rows = [
        _row(1, status="In Progress", priority="Major", assignee="PAT@example.com", due_date="15/10/2026"),
        _row(2, status="Closed", tags="ui; urgent", assignee="nobody@example.com", parent="W-1"),
        _row(3, assignee="outsider@example.com", description="Body", links=["https://nimble.example/w/3"]),
        {"row": 5, "external_id": "W-4", "title": "  "},
    ]
    status_ids = {s["name"]: s["id"] for s in world.project.model_dump(mode="json")["statuses"]}
    body = {"status_map": {"closed": status_ids["Done"]}, "date_format": "dmy", "file_name": "export.csv"}

    dry = await _import(client, world, rows, dry_run=True, **body)
    assert (dry["created"], dry["updated"], dry["skipped"]) == (3, 0, 1)
    assert await _tasks(client, world) == {}  # a dry run changes nothing

    result = await _import(client, world, rows, **body)
    assert (result["created"], result["updated"], result["unchanged"], result["skipped"]) == (3, 0, 0, 1)
    assert result["problems"] == [{"row": 5, "message": "no title"}]
    assert {(p["value"], p["reason"]) for p in result["unmatched_people"]} == {
        ("nobody@example.com", "not found in Glasshaus"),
        ("outsider@example.com", "can't open this project"),
    }
    tasks = await _tasks(client, world)
    one, two, three = tasks["Item 1"], tasks["Item 2"], tasks["Item 3"]
    assert one["status"]["name"] == "In progress" and one["priority"] == "high"
    assert one["assignee_id"] == str(pat.id) and one["due_date"] == "2026-10-15"
    assert two["status"]["name"] == "Done" and two["completed_at"] is not None
    assert two["tags"] == ["ui", "urgent"] and two["parent_id"] == one["id"] and two["assignee_id"] is None
    assert three["description"] == "Body\n\n**Links**\n- https://nimble.example/w/3"
    events = await events_for(str(world.project.id), "project.imported")
    assert events[-1]["data"]["created"] == 3 and events[-1]["data"]["file_name"] == "export.csv"
    assert await events_for(one["id"], "task.created") == []  # no per-task notifications or automations

    # The same file again: nothing new. A changed row updates its task; other fields stay.
    again = await _import(client, world, rows, **body)
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 3)
    rows[0]["title"] = "Item 1 renamed"
    rows[2]["links"] = []
    third = await _import(client, world, rows, **body)
    assert (third["created"], third["updated"], third["unchanged"]) == (0, 2, 1)
    tasks = await _tasks(client, world)
    assert tasks["Item 1 renamed"]["id"] == one["id"] and tasks["Item 1 renamed"]["key"] == one["key"]
    assert tasks["Item 3"]["description"] == "Body"
    assert len(tasks) == 3


async def test_only_mapped_fields_change_and_comments_import_once(client: AsyncClient) -> None:
    world = await make_world()
    first = await _import(
        client,
        world,
        [_row(1, description="Original", priority="low", comments=["First note", "First note", ""])],
        fields=[*ALL, "comments"],
    )
    assert first["comments_added"] == 1
    # A later file without the description or priority columns keeps them.
    later = await _import(
        client,
        world,
        [_row(1, comments=["First note", "Second note"])],
        fields=["external_id", "title", "comments"],
    )
    assert later["unchanged"] == 1 and later["comments_added"] == 1
    task = (await _tasks(client, world))["Item 1"]
    assert task["description"] == "Original" and task["priority"] == "low"
    r = await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=world.headers)
    assert [c["body"] for c in r.json()] == ["First note", "Second note"]


async def test_import_rejects_bad_rows_and_needs_edit_access(client: AsyncClient) -> None:
    world = await make_world()
    result = await _import(
        client,
        world,
        [
            _row(1, due_date="03/04/2026"),
            _row(2, due_date="2026-01-10", start_date="2026-02-01"),
            _row(3, links=["javascript:alert(1)"]),
            {**_row(1), "row": 9},
            _row(5, parent="W-404"),
        ],
        fields=[*ALL, "start_date", "links"],
    )
    messages = {p["row"]: p["message"] for p in result["problems"]}
    assert "choose a date format" in messages[2]
    assert messages[3] == "due date is before start date"
    assert "not an http(s) link" in messages[4]
    assert "appears more than once" in messages[9]
    assert "isn't in this file" in messages[6]
    assert result["created"] == 1  # only row W-5 (without its missing parent)

    viewer = await make_user(world.tenant, OrgRole.MEMBER)
    await add_member(client, world, viewer, "viewer")
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/import",
        json={"fields": ["title"], "rows": [{"row": 2, "title": "x"}]},
        headers=auth(await token_for(viewer)),
    )
    assert r.status_code in (403, 404)
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/import",
        json={"fields": ["status"], "rows": [{"row": 2, "title": "x"}]},
        headers=world.headers,
    )
    assert r.status_code == 422 and "title" in r.json()["detail"]


async def test_custom_fields_import(client: AsyncClient) -> None:
    world = await make_world()

    async def field(**body: Any) -> str:
        r = await client.post(f"/api/v1/projects/{world.project.id}/fields", json=body, headers=world.headers)
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    size = await field(
        name="Size", type="select", options=[{"id": "s", "label": "Small"}, {"id": "l", "label": "Large"}]
    )
    points = await field(name="Points", type="number")
    ship = await field(name="Ship", type="date")
    result = await _import(
        client,
        world,
        [
            _row(1, custom_fields={size: "large", points: "3,5", ship: "Oct 20, 2026"}),
            _row(2, custom_fields={size: "Huge"}),
        ],
        fields=["external_id", "title", f"cf:{size}", f"cf:{points}", f"cf:{ship}"],
    )
    assert result["created"] == 1 and "not one of its options" in result["problems"][0]["message"]
    task = (await _tasks(client, world))["Item 1"]
    assert task["custom_fields"] == {size: "l", points: 3.5, ship: "2026-10-20"}


def test_date_and_duration_parsing() -> None:
    assert parse_date("2026-10-15", "auto") == date(2026, 10, 15)
    assert parse_date("2026-10-15T09:00:00Z", "auto") == date(2026, 10, 15)
    assert parse_date("15/10/2026", "auto") == date(2026, 10, 15)
    assert parse_date("10/15/26", "auto") == date(2026, 10, 15)
    assert parse_date("03/04/2026", "dmy") == date(2026, 4, 3)
    assert parse_date("03/04/2026", "mdy") == date(2026, 3, 4)
    assert parse_date("12 Oct 2026", "auto") == date(2026, 10, 12)
    assert parse_date("Oct 12, 2026", "auto") == date(2026, 10, 12)
    assert parse_date("46310", "auto") == date(2026, 10, 15)
    assert parse_date("", "auto") is None
    for bad in ("31/02/2026", "soon", "03/04/2026"):
        with pytest.raises(RowError):
            parse_date(bad, "auto")
    assert parse_estimate("2.5") == 150
    assert parse_estimate("2,5") == 150
    assert parse_estimate("1h 30m") == 90
    assert parse_estimate("45m") == 45
    assert parse_estimate("") is None
    with pytest.raises(RowError):
        parse_estimate("a while")
