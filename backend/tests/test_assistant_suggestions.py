"""The project assistant's approval queue: rules, AI, notes, approve/edit/dismiss, staleness."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from glasshaus.ai import providers
from glasshaus.db import apply_tenant, system_session
from glasshaus.identity.models import User
from glasshaus.tasks.models import Task
from tests.factories import World, add_member, auth, create_task, make_user, make_world, token_for
from tests.test_ai import enable, fake  # noqa: F401 - fixture
from tests.test_assistant import account, turn_on
from tests.test_governance import audit

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def day(offset: int) -> str:
    return str(datetime.now(UTC).date() + timedelta(days=offset))


async def set_status(client: AsyncClient, world: World, task: dict[str, Any], category: str) -> None:
    statuses = (await client.get(f"/api/v1/projects/{world.project.id}", headers=world.headers)).json()[
        "statuses"
    ]
    status_id = next(s["id"] for s in statuses if s["category"] == category)
    r = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"status_id": status_id},
        headers=world.headers | {"If-Match": str(task["version"])},
    )  # fmt: skip
    assert r.status_code == 200, r.text


async def age(world: World, task_id: str, days: int) -> None:
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        await session.execute(
            update(Task).where(Task.id == task_id).values(updated_at=datetime.now(UTC) - timedelta(days=days))
        )


async def rename(world: World, user: User, name: str) -> None:
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        await session.execute(update(User).where(User.id == user.id).values(name=name))
    user.name = name


async def queue(
    client: AsyncClient, world: World, headers: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    r = await client.get(
        f"/api/v1/projects/{world.project.id}/assistant/suggestions", headers=headers or world.headers
    )
    assert r.status_code == 200, r.text
    data: list[dict[str, Any]] = r.json()
    return data


async def run_digest(client: AsyncClient, world: World) -> dict[str, Any]:
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/assistant/run", json={"kind": "digest"}, headers=world.headers
    )
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def url(world: World, suggestion: dict[str, Any], action: str) -> str:
    return f"/api/v1/projects/{world.project.id}/assistant/suggestions/{suggestion['id']}/{action}"


async def test_rules_fill_the_queue_and_approvals_act_as_the_assistant(client: AsyncClient) -> None:
    world = await make_world()
    editor = await make_user(world.tenant)
    viewer = await make_user(world.tenant)
    await add_member(client, world, editor, "editor")
    await add_member(client, world, viewer, "viewer")
    late = await create_task(
        client, world, title="Send invoice", due_date=day(-3), assignee_id=str(world.owner.id)
    )
    lost = await create_task(client, world, title="Book venue", due_date=day(-10))
    stuck = await create_task(client, world, title="Review copy", assignee_id=str(world.owner.id))
    await set_status(client, world, stuck, "in_progress")
    await age(world, stuck["id"], 6)
    await turn_on(client, world)  # stale after 3 days

    digest = await run_digest(client, world)
    found = await queue(client, world)
    by = {(s["kind"], s["task"]["title"]): s for s in found}
    assert set(by) == {
        ("comment", "Send invoice"),
        ("comment", "Review copy"),
        ("due_date", "Book venue"),
        ("assign", "Book venue"),
    }
    assert digest["content"]["suggestions"] == 4
    assert "3 days overdue" in by[("comment", "Send invoice")]["reason"]
    assert by[("assign", "Book venue")]["assignee"] == editor.name  # fewest open tasks
    assert by[("due_date", "Book venue")]["due_date"] == day(7)
    assert all(s["source"] == "rules" and s["status"] == "open" for s in found)
    await run_digest(client, world)
    assert len(await queue(client, world)) == 4  # no duplicates

    # Viewers see the queue but cannot decide.
    viewer_headers = auth(await token_for(viewer))
    assert len(await queue(client, world, viewer_headers)) == 4
    r = await client.post(
        url(world, by[("comment", "Send invoice")], "approve"), json={}, headers=viewer_headers
    )
    assert r.status_code in (403, 404)
    status = (
        await client.get(f"/api/v1/projects/{world.project.id}/assistant", headers=viewer_headers)
    ).json()
    assert status["can_approve"] is False

    # An editor approves an edited follow-up: posted by the assistant, signed with the approver.
    editor_headers = auth(await token_for(editor))
    r = await client.post(
        url(world, by[("comment", "Send invoice")], "approve"),
        json={"comment": "Can you send it today?"},
        headers=editor_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["decided_by"] == editor.name
    comments = (await client.get(f"/api/v1/tasks/{late['id']}/comments", headers=world.headers)).json()
    bot = await account(world)
    assert comments[-1]["author_id"] == str(bot.id)
    assert comments[-1]["body"].startswith("Can you send it today?")
    assert f"approved by {editor.name}" in comments[-1]["body"]
    entries = await audit(world, "assistant.suggestion_approved")
    assert entries and entries[-1].actor_id == editor.id
    again = await client.post(
        url(world, by[("comment", "Send invoice")], "approve"), json={}, headers=editor_headers
    )
    assert again.status_code == 409

    # Owner and date: applied as proposed.
    r = await client.post(
        url(world, by[("assign", "Book venue")], "approve"), json={}, headers=editor_headers
    )
    assert r.status_code == 200, r.text
    task = (await client.get(f"/api/v1/tasks/{lost['id']}", headers=world.headers)).json()
    assert task["assignee_id"] == str(editor.id)

    # The task changed since the date was suggested: set aside, not applied.
    task = (await client.get(f"/api/v1/tasks/{lost['id']}", headers=world.headers)).json()
    r = await client.patch(
        f"/api/v1/tasks/{lost['id']}", json={"due_date": day(2)},
        headers=world.headers | {"If-Match": str(task["version"])},
    )  # fmt: skip
    assert r.status_code == 200
    r = await client.post(
        url(world, by[("due_date", "Book venue")], "approve"), json={}, headers=editor_headers
    )
    assert r.status_code == 409 and "due date changed" in r.json()["detail"]
    decided = (
        await client.get(
            f"/api/v1/projects/{world.project.id}/assistant/suggestions?decided=true", headers=world.headers
        )
    ).json()
    assert {s["status"] for s in decided} == {"approved", "stale"}

    # Dismissed suggestions are not made again straight away.
    r = await client.post(url(world, by[("comment", "Review copy")], "dismiss"), headers=editor_headers)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    await run_digest(client, world)
    assert ("comment", "Review copy") not in {
        (s["kind"], s["task"]["title"]) for s in await queue(client, world)
    }


async def test_notes_become_tasks_after_approval(client: AsyncClient) -> None:
    world = await make_world()
    await turn_on(client, world)
    notes_url = f"/api/v1/projects/{world.project.id}/assistant/notes"
    r = await client.post(
        notes_url, json={"text": "We talked about the budget.\nNothing to do."}, headers=world.headers
    )
    assert r.status_code == 422 and "TODO:" in r.json()["detail"]
    notes = "Kick-off\n- [ ] Book the venue\nTODO: send invites\nAction item: order <badges>\nchit-chat"
    r = await client.post(notes_url, json={"text": notes}, headers=world.headers)
    assert r.status_code == 200, r.text
    proposed = r.json()
    assert [s["new_task"]["title"] for s in proposed] == ["Book the venue", "send invites", "order <badges>"]
    r = await client.post(
        url(world, proposed[1], "approve"),
        json={"new_task": {"title": "Send invites", "priority": "high", "due_date": day(5)}},
        headers=world.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"].startswith("Created ") and r.json()["task"]["title"] == "Send invites"
    task = (await client.get(f"/api/v1/tasks/{r.json()['task']['id']}", headers=world.headers)).json()
    assert task["priority"] == "high" and task["reporter_id"] == str((await account(world)).id)
    assert f"approved by {world.owner.name}" in task["description"]


async def test_ai_suggestions_are_checked_against_the_data(
    client: AsyncClient,
    fake: providers.FakeProvider,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await make_world()
    editor = await make_user(world.tenant)
    await rename(world, editor, "Sam Rivers")
    await add_member(client, world, editor, "editor")
    task = await create_task(
        client, world, title="Write spec", due_date=day(-2), assignee_id=str(world.owner.id)
    )
    other = await create_task(client, world, title="Plan launch", due_date=day(4))
    await enable(client, world, ai_features=["assistant"])
    await turn_on(client, world)
    monkeypatch.setitem(providers.FAKE_RESPONSES, "DigestOutput", {"summary": "Fine.", "focus": []})
    monkeypatch.setitem(
        providers.FAKE_RESPONSES,
        "SuggestOutput",
        {
            "suggestions": [
                {"kind": "comment", "task_key": task["key"].lower(), "comment": "Ping @boss@example.com, any news?",
                 "new_due_date": None, "assignee": None, "reason": "Two days late"},
                {"kind": "assign", "task_key": other["key"], "comment": None, "new_due_date": None,
                 "assignee": editor.name.upper(), "reason": "Has room"},
                {"kind": "assign", "task_key": other["key"], "comment": None, "new_due_date": None,
                 "assignee": "Someone Else", "reason": "Not on the project"},
                {"kind": "due_date", "task_key": "NOPE-1", "comment": None, "new_due_date": day(9),
                 "assignee": None, "reason": "Unknown task"},
                {"kind": "due_date", "task_key": task["key"], "comment": None, "new_due_date": day(-30),
                 "assignee": None, "reason": "In the past"},
            ]
        },
    )  # fmt: skip
    await run_digest(client, world)
    found = await queue(client, world)
    assert {(s["kind"], s["task"]["key"], s["source"]) for s in found} == {
        ("comment", task["key"], "ai"),
        ("assign", other["key"], "ai"),
    }
    comment = next(s for s in found if s["kind"] == "comment")["comment"]
    assert comment.startswith(f"@[{world.owner.name}](user:{world.owner.id}) ")
    assert "@boss@example.com" not in comment  # the model cannot mention people itself

    monkeypatch.setitem(
        providers.FAKE_RESPONSES,
        "NotesOutput",
        {"tasks": [{"title": "Draft agenda", "description": "For Monday", "priority": "medium",
                    "due_date": None, "assignee": editor.name}]},
    )  # fmt: skip
    r = await client.post(
        f"/api/v1/projects/{world.project.id}/assistant/notes",
        json={"text": "Sam will draft the agenda for Monday."},
        headers=world.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["new_task"]["assignee_id"] == str(editor.id)
    assert "untrusted" in fake.calls[-1]["system"]
