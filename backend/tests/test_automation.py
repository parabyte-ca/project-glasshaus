import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from glasshaus.automation import handlers, webhooks
from glasshaus.automation.models import AutomationRule, RecurringTask
from glasshaus.core.consumers import dispatch, load_handlers
from glasshaus.db import system_session
from tests.factories import World, add_member, auth, create_task, events_for, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def status_id(world: World, category: str) -> str:
    return next(str(s.id) for s in world.project.statuses if s.category.value == category)


async def make_rule(client: AsyncClient, world: World, **body: Any) -> dict[str, Any]:
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/automation-rules",
        json={"name": "Rule", **body},
        headers=world.headers,
    )
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def deliver(task_id: str, *types: str) -> None:
    load_handlers()
    for type_ in types:
        for event in await events_for(task_id, type_):
            await dispatch(event)


async def runs(client: AsyncClient, world: World, **params: str) -> list[dict[str, Any]]:
    r = await client.get(
        f"/api/v1/projects/{world.project.id}/automation-runs", params=params, headers=world.headers
    )
    assert r.status_code == 200, r.text
    data: list[dict[str, Any]] = r.json()
    return data


async def test_rule_permissions_and_validation(client: AsyncClient) -> None:
    world = await make_world()
    editor, viewer = await make_user(world.tenant), await make_user(world.tenant)
    await add_member(client, world, editor, "editor")
    await add_member(client, world, viewer, "viewer")
    body = {
        "name": "Close",
        "trigger": {"type": "task_created"},
        "actions": [{"type": "set_priority", "priority": "low"}],
    }
    url = f"/api/v1/projects/{world.project.id}/automation-rules"
    assert (await client.post(url, json=body, headers=auth(await token_for(editor)))).status_code == 403
    rule = await make_rule(client, world, **body)
    assert rule["webhook_secret"] and len(rule["webhook_secret"]) == 64
    seen = (await client.get(url, headers=auth(await token_for(viewer)))).json()
    assert [r["id"] for r in seen] == [rule["id"]] and seen[0]["webhook_secret"] is None
    bad = {**body, "actions": [{"type": "set_status", "status_id": str(uuid.uuid4())}]}
    assert (await client.post(url, json=bad, headers=world.headers)).status_code == 422
    other = await make_world()
    assert (
        await client.get(f"/api/v1/automation-rules/{rule['id']}", headers=other.headers)
    ).status_code == 404
    r = await client.patch(
        f"/api/v1/automation-rules/{rule['id']}", json={"enabled": False}, headers=world.headers
    )
    assert r.json()["enabled"] is False
    assert (
        await client.delete(f"/api/v1/automation-rules/{rule['id']}", headers=world.headers)
    ).status_code == 204


async def test_status_change_rule_runs_once_and_never_loops(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    await make_rule(
        client,
        world,
        name="Shipped",
        trigger={"type": "status_changed", "to_category": "done"},
        conditions=[{"field": "tags", "op": "contains", "value": "release"}],
        actions=[
            {"type": "add_tags", "tags": ["shipped"]},
            {"type": "post_comment", "body": "{{task.key}} shipped by {{rule.name}}"},
            {"type": "notify", "users": ["assignee"], "title": "{{task.key}} is done"},
        ],
    )
    # The same rule reacting to automation changes is still blocked for itself.
    await make_rule(
        client,
        world,
        name="Echo",
        trigger={"type": "task_updated", "field": "tags"},
        run_on_automation=True,
        actions=[{"type": "add_tags", "tags": ["echoed"]}],
    )
    plain = await create_task(client, world, title="No tag")
    task = await create_task(client, world, title="Release", tags=["release"], assignee_id=str(member.id))
    for t in (plain, task):
        r = await client.patch(
            f"/api/v1/tasks/{t['id']}", json={"status_id": status_id(world, "done")}, headers=world.headers
        )
        assert r.status_code == 200
    await deliver(plain["id"], "task.updated")
    await deliver(task["id"], "task.updated")
    await deliver(task["id"], "task.updated")  # redelivery of the same events: deduplicated

    current = (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()
    assert current["tags"] == ["echoed", "release", "shipped"]
    comments = (await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=world.headers)).json()
    assert [(c["body"], c["author_id"]) for c in comments] == [(f"{task['key']} shipped by Shipped", None)]
    notes = (await client.get("/api/v1/notifications", headers=auth(await token_for(member)))).json()
    assert any(n["kind"] == "automation" and n["title"] == f"{task['key']} is done" for n in notes["items"])
    log = await runs(client, world)
    assert sorted(r["rule_name"] for r in log) == ["Echo", "Shipped"]
    assert all(r["status"] == "success" and r["task_id"] == task["id"] for r in log)
    events = await events_for(task["id"], "task.updated")
    assert {e["actor"]["method"] for e in events} == {"token", "automation"}
    assert (await client.get(f"/api/v1/tasks/{plain['id']}", headers=world.headers)).json()["tags"] == []


async def test_failed_run_is_logged_and_retryable(client: AsyncClient) -> None:
    world = await make_world()
    field = (
        await client.post(
            f"/api/v1/projects/{world.project.id}/fields",
            json={"name": "Points", "type": "number"},
            headers=world.headers,
        )
    ).json()
    await make_rule(
        client,
        world,
        trigger={"type": "task_created"},
        actions=[
            {"type": "add_tags", "tags": ["seen"]},
            {"type": "set_custom_field", "field_id": field["id"], "value": "lots"},
        ],
    )
    task = await create_task(client, world)
    await deliver(task["id"], "task.created")
    [run] = await runs(client, world, status="failed")
    assert run["error"] and run["results"]["phase"] == "actions"
    # Atomic: the first action was rolled back with the failing one.
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()["tags"] == []
    retried = (await client.post(f"/api/v1/automation-runs/{run['id']}/retry", headers=world.headers)).json()
    assert retried["status"] == "failed" and retried["attempts"] == 2
    again = await client.post(f"/api/v1/automation-runs/{run['id']}/retry", headers=world.headers)
    assert again.json()["attempts"] == 3
    stranger = await make_world()
    assert (
        await client.post(f"/api/v1/automation-runs/{run['id']}/retry", headers=stranger.headers)
    ).status_code == 404


async def test_webhook_failure_retries_only_the_webhook(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await make_world()
    sent: list[tuple[str, dict[str, Any], str | None]] = []
    outcomes = iter([False, True])

    async def fake_send(
        url: str, payload: dict[str, Any], *, secret: str | None, event: str = "automation"
    ) -> webhooks.Delivery:
        sent.append((url, payload, secret))
        ok = next(outcomes)
        return webhooks.Delivery(
            url=url, ok=ok, status_code=200 if ok else 503, error=None if ok else "HTTP 503"
        )

    monkeypatch.setattr(webhooks, "send", fake_send)
    rule = await make_rule(
        client,
        world,
        trigger={"type": "task_created"},
        actions=[
            {"type": "add_tags", "tags": ["hooked"]},
            {"type": "webhook", "url": "https://hooks.example.com/x"},
        ],
    )
    task = await create_task(client, world)
    await deliver(task["id"], "task.created")
    [run] = await runs(client, world)
    assert run["status"] == "failed" and run["results"]["phase"] == "webhooks"
    assert run["results"]["webhooks"][0]["status_code"] == 503
    retried = (await client.post(f"/api/v1/automation-runs/{run['id']}/retry", headers=world.headers)).json()
    assert retried["status"] == "success" and retried["finished_at"]
    assert len(sent) == 2 and sent[0][2] == rule["webhook_secret"]
    assert sent[0][1]["task"]["key"] == task["key"] and sent[0][1]["rule"] == "Rule"
    # Actions ran once only.
    tags = (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()["tags"]
    assert tags == ["hooked"]


async def test_webhook_is_signed_and_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        headers = {
            k.lower(): v for k, v in (line.split(": ", 1) for line in head.split("\r\n")[1:] if ": " in line)
        }
        received["headers"] = headers
        received["body"] = await reader.readexactly(int(headers["content-length"]))
        writer.write(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(webhooks, "check_address", lambda ip, allow_private: None)
    async with server:
        result = await webhooks.send(f"http://localhost:{port}/hook?x=1", {"hello": "world"}, secret="s3cret")
    assert result.ok and result.status_code == 204
    h = received["headers"]
    assert h["host"] == f"localhost:{port}"
    ts = int(h["x-glasshaus-signature"].split(",")[0][2:])
    assert h["x-glasshaus-signature"] == webhooks.sign("s3cret", ts, received["body"])


async def test_dry_run(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world, priority="urgent", tags=["bug"])
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/automation-rules/test",
        headers=world.headers,
        json={
            "task": task["key"],
            "rule": {
                "name": "t",
                "trigger": {"type": "task_created"},
                "conditions": [
                    {"field": "priority", "op": "eq", "value": "urgent"},
                    {"field": "tags", "op": "contains", "value": "docs"},
                ],
                "actions": [{"type": "assign", "user": "reporter"}],
            },
        },
    )
    body = r.json()
    assert body["matched"] is False and [c["passed"] for c in body["conditions"]] == [True, False]
    assert body["planned_actions"] == ["assign: assign → reporter"]
    assert (await runs(client, world)) == []


async def test_scheduled_and_due_soon_rules(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    today = datetime.now(UTC).date()
    due = await create_task(
        client, world, due_date=str(today + timedelta(days=2)), assignee_id=str(member.id)
    )
    await create_task(client, world, due_date=str(today + timedelta(days=5)))
    await make_rule(
        client,
        world,
        name="Reminder",
        trigger={"type": "due_soon", "days_before": 2},
        actions=[{"type": "notify", "users": ["assignee"], "title": "{{task.key}} due {{task.due_date}}"}],
    )
    weekly = await make_rule(
        client,
        world,
        name="Weekly triage",
        trigger={"type": "scheduled", "schedule": {"frequency": "weekly", "weekday": 0, "hour": 8}},
        conditions=[{"field": "priority", "op": "eq", "value": "none"}],
        actions=[{"type": "set_priority", "priority": "low"}],
    )
    assert weekly["next_run_at"]
    assert await handlers.run_due_soon_rules() == 1
    assert await handlers.run_due_soon_rules() == 0  # once per task and due date
    assert await handlers.run_scheduled_rules() == 0  # not due yet
    async with system_session() as session:
        await session.execute(
            update(AutomationRule)
            .where(AutomationRule.id == uuid.UUID(weekly["id"]))
            .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    assert await handlers.run_scheduled_rules() == 2
    assert await handlers.run_scheduled_rules() == 0
    tasks = (
        await client.get("/api/v1/tasks", params={"project_id": str(world.project.id)}, headers=world.headers)
    ).json()
    assert {t["priority"] for t in tasks["items"]} == {"low"}
    after = (await client.get(f"/api/v1/automation-rules/{weekly['id']}", headers=world.headers)).json()
    assert datetime.fromisoformat(after["next_run_at"]) > datetime.now(UTC)
    notes = (await client.get("/api/v1/notifications", headers=auth(await token_for(member)))).json()["items"]
    assert [n["title"] for n in notes if n["kind"] == "automation"] == [
        f"{due['key']} due {today + timedelta(days=2)}"
    ]


async def test_recurring_tasks(client: AsyncClient) -> None:
    world = await make_world()
    url = f"/api/v1/projects/{world.project.id}/recurring-tasks"
    body = {
        "template": {"title": "Patch the homelab", "tags": ["ops"], "due_in_days": 3, "priority": "high"},
        "schedule": {"frequency": "monthly", "day": 1, "hour": 6, "timezone": "America/Toronto"},
    }
    item = (await client.post(url, json=body, headers=world.headers)).json()
    assert datetime.fromisoformat(item["next_run_at"]) > datetime.now(UTC)
    async with system_session() as session:
        await session.execute(
            update(RecurringTask)
            .where(RecurringTask.id == uuid.UUID(item["id"]))
            .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    assert await handlers.run_recurring_tasks() == 1
    assert await handlers.run_recurring_tasks() == 0
    [listed] = (await client.get(url, headers=world.headers)).json()
    assert listed["last_task_id"]
    created = (await client.get(f"/api/v1/tasks/{listed['last_task_id']}", headers=world.headers)).json()
    assert (
        created["title"] == "Patch the homelab"
        and created["tags"] == ["ops"]
        and created["priority"] == "high"
    )
    assert date.fromisoformat(created["due_date"]) - date.fromisoformat(created["start_date"]) == timedelta(
        days=3
    )
    assert (
        await client.delete(f"/api/v1/recurring-tasks/{item['id']}", headers=world.headers)
    ).status_code == 204


async def test_project_templates(client: AsyncClient) -> None:
    world = await make_world()
    pid = world.project.id
    review = (
        await client.post(
            f"/api/v1/projects/{pid}/statuses",
            json={"name": "Review", "category": "in_progress"},
            headers=world.headers,
        )
    ).json()
    field = (
        await client.post(
            f"/api/v1/projects/{pid}/fields",
            json={
                "name": "Size",
                "type": "select",
                "options": [{"id": "s", "label": "S"}, {"id": "l", "label": "L"}],
            },
            headers=world.headers,
        )
    ).json()
    parent = await create_task(
        client,
        world,
        title="Plan",
        start_date="2026-01-05",
        due_date="2026-01-09",
        custom_fields={field["id"]: "l"},
    )
    child = await create_task(
        client, world, title="Draft", parent_id=parent["id"], status_id=review["id"], due_date="2026-01-12"
    )
    r = await client.post(
        "/api/v1/dependencies",
        json={"predecessor": parent["key"], "successor": child["key"]},
        headers=world.headers,
    )
    assert r.status_code == 201, r.text
    await make_rule(
        client,
        world,
        trigger={"type": "status_changed", "to_status_id": review["id"]},
        conditions=[{"field": f"cf:{field['id']}", "op": "eq", "value": "l"}],
        actions=[{"type": "add_tags", "tags": ["big"]}],
    )
    tpl = await client.post(
        "/api/v1/project-templates", json={"project_id": str(pid), "name": "Launch"}, headers=world.headers
    )
    assert tpl.status_code == 201, tpl.text
    assert tpl.json()["summary"] | {} == {
        "statuses": 6,
        "fields": 1,
        "views": 0,
        "tasks": 2,
        "dependencies": 1,
        "rules": 1,
        "recurring": 0,
    }
    dup = await client.post(
        "/api/v1/project-templates", json={"project_id": str(pid), "name": "Launch"}, headers=world.headers
    )
    assert dup.status_code == 409

    made = await client.post(
        f"/api/v1/project-templates/{tpl.json()['id']}/instantiate",
        json={
            "workspace_id": str(world.workspace_id),
            "key": "NEW" + uuid.uuid4().hex[:3].upper(),
            "name": "Launch 2",
            "start_date": "2026-03-02",
        },
        headers=world.headers,
    )
    assert made.status_code == 201, made.text
    project = made.json()
    assert "Review" in [s["name"] for s in project["statuses"]]
    new_review = next(s["id"] for s in project["statuses"] if s["name"] == "Review")
    tasks = (
        await client.get("/api/v1/tasks", params={"project_id": project["id"]}, headers=world.headers)
    ).json()["items"]
    by_title = {t["title"]: t for t in tasks}
    assert by_title["Plan"]["start_date"] == "2026-03-02" and by_title["Draft"]["due_date"] == "2026-03-09"
    assert (
        by_title["Draft"]["parent_id"] == by_title["Plan"]["id"]
        and by_title["Draft"]["status"]["id"] == new_review
    )
    [new_field] = (await client.get(f"/api/v1/projects/{project['id']}/fields", headers=world.headers)).json()
    assert by_title["Plan"]["custom_fields"] == {new_field["id"]: "l"}
    deps = (await client.get(f"/api/v1/projects/{project['id']}/dependencies", headers=world.headers)).json()
    assert len(deps) == 1
    [rule] = (
        await client.get(f"/api/v1/projects/{project['id']}/automation-rules", headers=world.headers)
    ).json()
    assert (
        rule["trigger"]["to_status_id"] == new_review
        and rule["conditions"][0]["field"] == f"cf:{new_field['id']}"
    )
    # Rules never react to the copy that created them.
    for t in tasks:
        await deliver(t["id"], "task.created", "task.updated")
    assert (
        await client.get(f"/api/v1/projects/{project['id']}/automation-runs", headers=world.headers)
    ).json() == []
    assert (
        await client.delete(f"/api/v1/project-templates/{tpl.json()['id']}", headers=world.headers)
    ).status_code == 204
