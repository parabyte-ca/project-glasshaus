"""Slack and Teams: scheduled report/status posts to channels, and the /glasshaus Slack command."""

import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient

from glasshaus.integrations import posts, slack_command
from tests.factories import auth, create_task, make_user, make_world, token_for
from tests.test_ai import enable, fake  # noqa: F401 - fixture
from tests.test_connectors import Outbox, connect, outbox  # noqa: F401 - fixture

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 9, "minute": 0, "timezone": "UTC"}
SIGNING = "slack-signing-secret"


async def test_report_and_status_posts(client: AsyncClient, outbox: Outbox) -> None:  # noqa: F811
    world = await make_world()
    other = await client.post(
        "/api/v1/projects",
        json={"workspace_id": str(world.workspace_id), "key": "OPS", "name": "Ops"},
        headers=world.headers,
    )
    assert other.status_code == 201, other.text
    await create_task(client, world, title="Write <brief> & send", priority="high", due_date="2026-01-02")
    await client.post(
        "/api/v1/tasks", json={"project_id": other.json()["id"], "title": "Other"}, headers=world.headers
    )
    report = (
        await client.post(
            "/api/v1/reports",
            json={"name": "By priority", "definition": {"group_by": ["priority"], "measures": ["count"]}},
            headers=world.headers,
        )
    ).json()
    # A Slack channel for this project only, and an organization-wide Teams channel.
    slack = await connect(client, world, kind="slack", name="#web", project_id=str(world.project.id),
                          url="https://hooks.slack.com/services/T0/B0/x")  # fmt: skip
    teams = await connect(
        client, world, kind="teams", name="Teams", url="https://example.webhook.office.com/x"
    )
    webhook = await connect(client, world, kind="webhook", name="Hook", url="https://example.com/hook")

    url = f"/api/v1/integrations/{slack['id']}/posts"
    r = await client.post(url, json={"kind": "report", "report_id": report["id"], "schedule": WEEKLY},
                          headers=world.headers)  # fmt: skip
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["title"] == "By priority" and post["kind"] == "report"
    bad = {"kind": "status", "project_id": other.json()["id"], "schedule": WEEKLY}
    r = await client.post(url, json=bad, headers=world.headers)
    assert r.status_code == 422 and "another project" in r.json()["detail"]
    r = await client.post(f"/api/v1/integrations/{webhook['id']}/posts", json=bad, headers=world.headers)
    assert r.status_code == 422 and "Slack or Microsoft Teams" in r.json()["detail"]
    member = await make_user(world.tenant)
    r = await client.post(url, json=bad, headers=auth(await token_for(member)))
    assert r.status_code in (403, 404)

    # Send now: the project channel only counts this project's task.
    sent = await client.post(f"{url}/{post['id']}/send", headers=world.headers)
    assert sent.status_code == 200 and sent.json()["status"] == "success", sent.text
    text = outbox.sent[-1]["payload"]["blocks"][0]["text"]["text"]
    assert "*By priority*" in text and "```\nPriority  Tasks\nHigh          1\nTotal         1\n```" in text
    assert outbox.sent[-1]["event"] == "report.posted"

    status = {"kind": "status", "project_id": str(world.project.id), "schedule": WEEKLY}
    r = await client.post(f"/api/v1/integrations/{teams['id']}/posts", json=status, headers=world.headers)
    assert r.status_code == 201 and r.json()["title"].startswith(world.project.key)
    due = datetime.fromisoformat(r.json()["next_run_at"])
    outbox.sent.clear()
    assert await posts.send_due(due + timedelta(seconds=5)) >= 2  # both posts (and other tests' ones)
    card = next(s for s in outbox.sent if s["event"] == "status.posted")["payload"]["attachments"][0][
        "content"
    ]
    texts = " ".join(b.get("text", "") for b in card["body"])
    assert "Overdue" in texts and "Write <brief> & send" in texts and "Open 1" in texts
    listed = (await client.get(url, headers=world.headers)).json()
    assert listed[0]["last_sent_at"] is not None and listed[0]["last_error"] is None
    assert datetime.fromisoformat(listed[0]["next_run_at"]) > due

    # The report is deleted: the post ends with it.
    await client.delete(f"/api/v1/reports/{report['id']}", headers=world.headers)
    assert (await client.get(url, headers=world.headers)).json() == []
    r = await client.delete(
        f"/api/v1/integrations/{teams['id']}/posts/{listed[0]['id']}", headers=world.headers
    )
    assert r.status_code == 404


def signed(
    body: dict[str, str], *, secret: str = SIGNING, stamp: int | None = None
) -> tuple[bytes, dict[str, str]]:
    raw = urlencode(body).encode()
    ts = str(stamp or int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        "Content-Type": "application/x-www-form-urlencoded",
    }


async def test_slack_command(client: AsyncClient, outbox: Outbox, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    world = await make_world()
    task = await create_task(client, world, title="Renew <certs>", due_date="2026-01-05")
    await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"assignee_id": str(world.owner.id)}, headers=world.headers
    )
    await client.post(
        "/api/v1/reports",
        json={"name": "Open work", "definition": {"measures": ["open"]}},
        headers=world.headers,
    )
    r = await client.post(
        "/api/v1/integrations", json={"kind": "slack_command", "name": "Slack"}, headers=world.headers
    )
    assert r.status_code == 422
    member = await make_user(world.tenant)
    body: dict[str, Any] = {"kind": "slack_command", "name": "Slack", "secret": SIGNING, "token": "xoxb-1"}
    r = await client.post("/api/v1/integrations", json=body, headers=auth(await token_for(member)))
    assert r.status_code == 403
    integration = await connect(client, world, **body)
    endpoint = f"/api/v1/integrations/{integration['id']}/slack"
    assert integration["inbound_url"].endswith(endpoint) and "xoxb" not in str(integration)

    emails = {"U1": world.owner.email, "U2": "stranger@example.com"}

    async def fake_email(token: str, user: str) -> str | None:
        assert token == "xoxb-1"
        return emails.get(user)

    monkeypatch.setattr(slack_command, "slack_email", fake_email)

    async def ask(text: str, user: str = "U1") -> dict[str, Any]:
        raw, headers = signed(
            {"user_id": user, "text": text, "response_url": "https://hooks.slack.com/commands/T0/1/x"}
        )
        r = await client.post(endpoint, content=raw, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"response_type": "ephemeral", "text": "Looking that up…"}
        reply = outbox.sent[-1]
        assert reply["url"] == "https://hooks.slack.com/commands/T0/1/x"
        payload: dict[str, Any] = reply["payload"]
        assert payload["response_type"] == "ephemeral"
        return payload

    def text_of(payload: dict[str, Any]) -> str:
        return str(payload["blocks"][0]["text"]["text"])

    assert "/glasshaus my" in text_of(await ask("help"))
    mine = text_of(await ask("my"))
    assert task["key"] in mine and "Renew &lt;certs&gt;" in mine and "due 2026-01-05" in mine
    one = await ask(task["key"].lower())
    assert "Renew &lt;certs&gt;" in text_of(one) and f"?task={task['id']}" in str(one["blocks"][1])
    assert "Open work" in text_of(await ask("report open"))
    assert "No saved report" in text_of(await ask("report nothing like it"))
    assert "AI assistant is turned on" in text_of(await ask("who is busiest?"))
    assert "isn't linked" in text_of(await ask("my", user="U2"))
    # Someone who cannot see the project gets nothing about its tasks.
    emails["U3"] = member.email
    assert "can't find" in text_of(await ask(task["key"], user="U3"))

    raw, headers = signed({"ssl_check": "1"})
    assert (await client.post(endpoint, content=raw, headers=headers)).json() == {}
    raw, headers = signed({"text": "my"}, secret="wrong")
    assert (await client.post(endpoint, content=raw, headers=headers)).status_code == 401
    raw, headers = signed({"text": "my"}, stamp=int(time.time()) - 600)
    assert (await client.post(endpoint, content=raw, headers=headers)).status_code == 401
    raw, headers = signed({"text": "my", "response_url": "https://evil.example/x"})
    assert (await client.post(endpoint, content=raw, headers=headers)).status_code == 422


async def test_slack_questions_use_the_assistant(
    client: AsyncClient,
    outbox: Outbox,  # noqa: F811
    fake: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await make_world()
    await enable(client, world, ai_features=["search"])
    await create_task(client, world, title="Late thing")
    integration = await connect(client, world, kind="slack_command", name="Slack", secret=SIGNING, token="x")

    async def fake_email(token: str, user: str) -> str:
        return world.owner.email

    monkeypatch.setattr(slack_command, "slack_email", fake_email)
    raw, headers = signed(
        {"user_id": "U1", "text": "what is late?", "response_url": "https://hooks.slack.com/c/1"}
    )
    r = await client.post(f"/api/v1/integrations/{integration['id']}/slack", content=raw, headers=headers)
    assert r.status_code == 200
    reply = outbox.sent[-1]["payload"]
    assert reply["response_type"] == "ephemeral" and "blocks" in reply
    assert fake.calls[-1]["output"] == "SearchFilters" and "what is late?" in fake.calls[-1]["prompt"]
