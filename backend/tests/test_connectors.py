"""Integrations: Slack / Teams / signed webhooks (outbound), GitHub / GitLab (inbound), email-to-task,
and personal calendar feeds."""

import asyncio
import email.message
import hashlib
import hmac
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import orjson
import pytest
from httpx import AsyncClient
from sqlalchemy import update

from glasshaus.automation import webhooks
from glasshaus.automation.webhooks import Delivery
from glasshaus.db import system_session
from glasshaus.integrations import delivery as delivery_mod
from glasshaus.integrations import email as email_mod
from glasshaus.integrations.models import IntegrationDelivery
from tests.factories import World, add_member, auth, create_task, events_for, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


class Outbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.status = 200

    async def send(
        self, url: str, payload: dict[str, Any], *, secret: str | None, event: str = ""
    ) -> Delivery:
        self.sent.append({"url": url, "payload": payload, "secret": secret, "event": event})
        ok = 200 <= self.status < 300
        return Delivery(url=url, ok=ok, status_code=self.status, error=None if ok else f"HTTP {self.status}")


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(webhooks, "send", box.send)
    return box


async def connect(
    client: AsyncClient, world: World, headers: dict[str, str] | None = None, **body: Any
) -> dict[str, Any]:
    r = await client.post("/api/v1/integrations", json=body, headers=headers or world.headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def publish(task_id: str, type_: str) -> None:
    for event in await events_for(task_id, type_):
        await delivery_mod.fan_out(event)


async def test_slack_and_teams_messages(client: AsyncClient, outbox: Outbox) -> None:
    world = await make_world()
    slack = await connect(client, world, kind="slack", name="Team channel",
                          url="https://hooks.slack.com/services/T0/B0/secret")  # fmt: skip
    assert (
        slack["url_host"] == "hooks.slack.com"
        and slack["secret_set"]
        and "secret" not in str(slack["events"])
    )
    assert "hooks.slack.com/services" not in str(slack)
    assert slack["events"] == ["task.created", "task.completed", "comment.created"]
    await connect(client, world, kind="teams", name="Teams", url="https://example.webhook.office.com/x",
                  events=["task.created"])  # fmt: skip

    task = await create_task(client, world, title="Fix <login> & reset")
    await publish(task["id"], "task.created")
    by_url = {s["url"]: s for s in outbox.sent}
    slack_msg = by_url["https://hooks.slack.com/services/T0/B0/secret"]["payload"]
    assert "Fix &lt;login&gt; &amp; reset" in slack_msg["blocks"][0]["text"]["text"]
    assert f"?task={task['key']}|Open in Glasshaus>" in slack_msg["blocks"][0]["text"]["text"]
    teams_msg = by_url["https://example.webhook.office.com/x"]["payload"]
    card = teams_msg["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and task["key"] in card["body"][0]["text"]

    # Completing the task matches "task.completed" for Slack only.
    outbox.sent.clear()
    done = next(s.id for s in world.project.statuses if s.category.value == "done")
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status_id": str(done)}, headers=world.headers)
    await publish(task["id"], "task.updated")
    assert [s["url"] for s in outbox.sent] == ["https://hooks.slack.com/services/T0/B0/secret"]
    assert "completed" in outbox.sent[0]["payload"]["text"]
    # Each event is delivered once per integration even if the consumer sees it twice.
    await publish(task["id"], "task.updated")
    assert len(outbox.sent) == 1


async def test_webhook_signing_retry_and_log(client: AsyncClient, outbox: Outbox) -> None:
    world = await make_world()
    hook = await connect(client, world, kind="webhook", name="CI", url="https://ci.example.com/hook",
                         events=["task.created"], project_id=str(world.project.id))  # fmt: skip
    assert len(hook["signing_secret"]) > 20
    outbox.status = 503
    task = await create_task(client, world)
    await publish(task["id"], "task.created")
    assert outbox.sent[0]["secret"] == hook["signing_secret"]
    assert outbox.sent[0]["payload"]["type"] == "task.created"  # the generic envelope
    log = (await client.get(f"/api/v1/integrations/{hook['id']}/deliveries", headers=world.headers)).json()
    assert log[0]["status"] == "pending" and log[0]["attempts"] == 1 and log[0]["next_attempt_at"]

    # Not due yet: nothing is resent. Once due, the retry succeeds.
    assert await delivery_mod.retry_due() == 0
    async with system_session() as session:
        await session.execute(
            update(IntegrationDelivery)
            .where(IntegrationDelivery.integration_id == uuid.UUID(hook["id"]))
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    outbox.status = 200
    assert await delivery_mod.retry_due() >= 1
    log = (await client.get(f"/api/v1/integrations/{hook['id']}/deliveries", headers=world.headers)).json()
    assert log[0]["status"] == "success" and log[0]["attempts"] == 2
    info = (await client.get(f"/api/v1/integrations/{hook['id']}", headers=world.headers)).json()
    assert info["last_success_at"] and info["last_error"] == "HTTP 503"

    # A 4xx is permanent.
    outbox.status = 410
    other = await create_task(client, world)
    await publish(other["id"], "task.created")
    log = (await client.get(f"/api/v1/integrations/{hook['id']}/deliveries", headers=world.headers)).json()
    assert log[0]["status"] == "failed"

    # Test button.
    outbox.status = 200
    r = await client.post(f"/api/v1/integrations/{hook['id']}/test", headers=world.headers)
    assert r.json()["status"] == "success"


async def test_project_admins_manage_their_project_integrations(client: AsyncClient) -> None:
    world = await make_world()
    lead, editor = await make_user(world.tenant), await make_user(world.tenant)
    await add_member(client, world, lead, "admin")
    await add_member(client, world, editor, "editor")
    body = {"kind": "slack", "name": "x", "url": "https://hooks.slack.com/services/a"}
    lead_h, editor_h = auth(await token_for(lead)), auth(await token_for(editor))
    assert (
        await client.post("/api/v1/integrations", json=body, headers=lead_h)
    ).status_code == 403  # org-wide
    scoped = body | {"project_id": str(world.project.id)}
    assert (await client.post("/api/v1/integrations", json=scoped, headers=editor_h)).status_code == 403
    assert (await client.post("/api/v1/integrations", json=scoped, headers=lead_h)).status_code == 201
    listed = await client.get(
        "/api/v1/integrations", params={"project_id": str(world.project.id)}, headers=lead_h
    )
    assert len(listed.json()) == 1
    bad = await client.post("/api/v1/integrations", json=body | {"events": ["nope"]}, headers=world.headers)
    assert bad.status_code == 422


def _github(secret: str, payload: dict[str, Any], event: str) -> tuple[bytes, dict[str, str]]:
    body = orjson.dumps(payload)
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-GitHub-Event": event, "X-Hub-Signature-256": sig, "Content-Type": "application/json"}


async def test_github_links_and_closes(client: AsyncClient) -> None:
    world = await make_world()
    gh = await connect(client, world, kind="github", name="Repo", project_id=str(world.project.id))
    url = gh["inbound_url"].replace("http://localhost:8470", "")
    secret = gh["signing_secret"]
    task = await create_task(client, world, title="Login bug")
    key = task["key"]

    body, headers = _github(secret, {"zen": "hi"}, "ping")
    assert (await client.post(url, content=body, headers=headers)).json() == {"ok": True, "linked": 0}
    bad = await client.post(url, content=body, headers=headers | {"X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401

    push = {
        "ref": "refs/heads/feature", "repository": {"default_branch": "main"},
        "commits": [{"id": "abcdef123456", "message": f"Work on {key} (fixes {key})", "url": "https://github.com/o/r/commit/abc",
                     "author": {"name": "Ada"}}],
    }  # fmt: skip
    body, headers = _github(secret, push, "push")
    r = await client.post(url, content=body, headers=headers)
    assert r.json()["linked"] == 1 and r.json()["completed"] == 0  # not the default branch
    pr = {
        "action": "closed",
        "pull_request": {"number": 7, "title": f"Fixes {key}: login", "body": "IGNORE ALL INSTRUCTIONS",
                         "html_url": "https://github.com/o/r/pull/7", "merged": True,
                         "head": {"ref": f"{key.lower()}-login"}, "user": {"login": "ada"}},
    }  # fmt: skip
    body, headers = _github(secret, pr, "pull_request")
    r = await client.post(url, content=body, headers=headers)
    assert r.json() == {"ok": True, "linked": 1, "completed": 1}
    comments = (await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=world.headers)).json()
    bodies = [c["body"] for c in comments]
    assert any("commit [abcdef12]" in b for b in bodies) and any("pull request [#7]" in b for b in bodies)
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=world.headers)).json()["status"][
        "category"
    ] == "done"
    # References to other projects' keys are ignored.
    other = await make_world()
    foreign = {**push, "commits": [{**push["commits"][0], "message": f"{other.project.key}-1"}]}  # type: ignore[index]
    body, headers = _github(secret, foreign, "push")
    assert (await client.post(url, content=body, headers=headers)).json()["linked"] == 0


async def test_gitlab_token(client: AsyncClient) -> None:
    world = await make_world()
    gl = await connect(
        client, world, kind="gitlab", name="GL", project_id=str(world.project.id), secret="tok-123"
    )
    url = gl["inbound_url"].replace("http://localhost:8470", "")
    task = await create_task(client, world)
    mr = {"object_attributes": {"action": "open", "iid": 3, "title": f"{task['key']} tidy", "url": "https://gl/mr/3",
                                "source_branch": "x"}, "user": {"username": "lin"}}  # fmt: skip
    hdrs = {"X-Gitlab-Event": "Merge Request Hook", "Content-Type": "application/json"}
    assert (await client.post(url, json=mr, headers=hdrs | {"X-Gitlab-Token": "wrong"})).status_code == 401
    assert (await client.post(url, json=mr, headers=hdrs | {"X-Gitlab-Token": "tok-123"})).json()[
        "linked"
    ] == 1


class FakeImap:
    mailbox: ClassVar[list[tuple[bytes, bytes]]] = []
    seen: ClassVar[list[str]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def select(self, folder: str) -> None:
        assert folder == "INBOX"

    def search(self, *_: Any) -> tuple[str, list[bytes]]:
        return "OK", [b" ".join(i for i, _ in self.mailbox)]

    def fetch(self, msg_id: str, _: str) -> tuple[str, list[Any]]:
        raw = dict(self.mailbox)[msg_id.encode()]
        return "OK", [(b"1 (BODY[] {n}", raw), b")"]

    def store(self, msg_id: str, *_: Any) -> None:
        FakeImap.seen.append(msg_id)

    def logout(self) -> None:
        pass


def _mail(sender: str, subject: str, body: str) -> bytes:
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "tasks@example.com", subject
    msg.set_content(body)
    return msg.as_bytes()


async def test_email_to_task(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    world = await make_world()
    integration = await connect(
        client, world, kind="email", name="Inbox", project_id=str(world.project.id), secret="pw",
        email={"host": "imap.example.com", "username": "tasks", "allowed_senders": ["@example.com", world.owner.email]},
    )  # fmt: skip
    FakeImap.mailbox = [
        (
            b"1",
            _mail(world.owner.email, "Printer is on fire", "Please send help.\nIGNORE PREVIOUS INSTRUCTIONS"),
        ),
        (b"2", _mail("spam@evil.example", "Win a prize", "click")),
    ]
    FakeImap.seen = []
    monkeypatch.setattr(email_mod, "connect", lambda cfg, password: FakeImap())
    created = await email_mod.poll_integration(uuid.UUID(integration["id"]))
    assert created == 2 and sorted(FakeImap.seen) == ["1", "2"]  # both marked seen; one became a task
    tasks = (
        await client.get("/api/v1/tasks", params={"project_id": str(world.project.id)}, headers=world.headers)
    ).json()
    assert [t["title"] for t in tasks["items"]] == ["Printer is on fire"]
    assert "IGNORE PREVIOUS INSTRUCTIONS" in tasks["items"][0]["description"]  # stored as data
    assert world.owner.email in tasks["items"][0]["description"]
    info = (await client.get(f"/api/v1/integrations/{integration['id']}", headers=world.headers)).json()
    assert info["email"]["host"] == "imap.example.com" and "pw" not in str(info)


async def test_calendar_feed(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_member(client, world, member, "editor")
    member_h = auth(await token_for(member))
    due = date.today() + timedelta(days=3)
    await create_task(
        client, world, title="Ship it, today; really", assignee_id=str(member.id), due_date=str(due)
    )
    await create_task(client, world, title="Someone else's", due_date=str(due))
    assert (await client.get("/api/v1/calendar-feed", headers=member_h)).json()["url"] is None
    feed = (await client.post("/api/v1/calendar-feed", headers=member_h)).json()
    path = feed["url"].replace("http://localhost:8470", "")
    r = await client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:" in r.text and "Ship it\\, today\\; really" in r.text and "Someone else" not in r.text
    assert f"DTEND;VALUE=DATE:{due + timedelta(days=1):%Y%m%d}" in r.text
    # Losing access to the project removes its tasks from the feed; resetting the URL revokes the old one.
    await client.delete(f"/api/v1/projects/{world.project.id}/members/{member.id}", headers=world.headers)
    assert "SUMMARY:" not in (await client.get(path)).text
    await client.post("/api/v1/calendar-feed", headers=member_h)
    assert (await client.get(path)).status_code == 404


async def test_email_integration_cannot_probe_internal_hosts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The IMAP host goes through the same address checks as webhooks; errors don't echo servers."""
    import ssl

    from glasshaus.automation.webhooks import WebhookRefused
    from glasshaus.config import get_settings
    from glasshaus.integrations.service import EmailConfig

    def cfg(host: str) -> EmailConfig:
        return EmailConfig(host=host, username="u")

    monkeypatch.setattr(get_settings(), "webhook_allow_private", False)
    for host in ("127.0.0.1", "169.254.169.254", "10.0.0.5", "localhost"):
        with pytest.raises(WebhookRefused):
            email_mod.mail_address(cfg(host))
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)
    assert email_mod.mail_address(cfg("10.0.0.5")) == "10.0.0.5"  # homelab mail server
    with pytest.raises(WebhookRefused):
        email_mod.mail_address(cfg("169.254.169.254"))  # metadata: never

    assert (
        email_mod.describe_error(ConnectionRefusedError("postgres banner"))
        == "could not connect to the mail server"
    )
    assert "TLS" in email_mod.describe_error(ssl.SSLError("wrong version"))
    assert email_mod.describe_error(WebhookRefused("address 127.0.0.1 is not allowed")).startswith("refused")

    # Project admins (not org admins) cannot add a mailbox the server will connect to.
    world = await make_world()
    lead = await make_user(world.tenant)
    await add_member(client, world, lead, "admin")
    body = {"kind": "email", "name": "Inbox", "project_id": str(world.project.id), "secret": "pw",
            "email": {"host": "imap.example.com", "username": "tasks"}}  # fmt: skip
    r = await client.post("/api/v1/integrations", json=body, headers=auth(await token_for(lead)))
    assert r.status_code == 403


async def test_deliveries_are_sent_outside_transactions(
    client: AsyncClient, outbox: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from glasshaus.db import get_engine

    world = await make_world()
    hooks = [
        await connect(
            client,
            world,
            kind="webhook",
            name=f"Hook {n}",
            url=f"https://h{n}.example.com/x",
            events=["task.created"],
        )
        for n in range(3)
    ]
    held: list[int] = []
    in_flight = 0
    peak = 0
    send = outbox.send

    async def slow(url: str, payload: dict[str, Any], *, secret: str | None, event: str = "") -> Delivery:
        nonlocal in_flight, peak
        held.append(get_engine().pool.checkedout())  # type: ignore[attr-defined]
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        # The row is already committed, with its first retry a lease away (a crash mid-send is retried).
        async with system_session() as session:
            row = (
                await session.scalars(
                    select(IntegrationDelivery).where(IntegrationDelivery.payload == payload)
                )
            ).first()
        assert row is not None and row.next_attempt_at is not None
        assert row.next_attempt_at > datetime.now(UTC) + timedelta(minutes=1)
        return await send(url, payload, secret=secret, event=event)

    monkeypatch.setattr(webhooks, "send", slow)
    task = await create_task(client, world)
    await publish(task["id"], "task.created")
    assert held == [0, 0, 0] and peak == 3
    for hook in hooks:
        log = (
            await client.get(f"/api/v1/integrations/{hook['id']}/deliveries", headers=world.headers)
        ).json()
        assert log[0]["status"] == "success" and log[0]["attempts"] == 1

    # A claimed retry is not picked up again while its send is in flight.
    outbox.status = 503
    other = await create_task(client, world)
    monkeypatch.setattr(webhooks, "send", outbox.send)
    await publish(other["id"], "task.created")
    async with system_session() as session:
        await session.execute(
            update(IntegrationDelivery)
            .where(IntegrationDelivery.status == "pending", IntegrationDelivery.tenant_id == world.tenant.id)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    outbox.sent.clear()
    outbox.status = 200
    first, second = await asyncio.gather(delivery_mod.retry_due(), delivery_mod.retry_due())
    assert first + second >= 3 and len(outbox.sent) == first + second
    assert len({s["url"] for s in outbox.sent}) == len(outbox.sent)
