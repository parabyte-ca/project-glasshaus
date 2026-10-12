"""Scheduled report emails: subscribe, send on schedule with the subscriber's access, send now."""

import asyncio
import smtplib
from collections.abc import Iterator
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import update

from glasshaus import mail
from glasshaus.config import get_settings
from glasshaus.core.rbac import Scope
from glasshaus.db import system_session
from glasshaus.identity.models import User
from glasshaus.reports.subscriptions import send_due
from tests.factories import auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 8, "minute": 0, "timezone": "America/Toronto"}


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EmailMessage]]:
    monkeypatch.setattr(get_settings(), "smtp_host", "memory")
    mail.OUTBOX.clear()
    yield mail.OUTBOX
    mail.OUTBOX.clear()


async def report(client: AsyncClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    payload = {"name": "By priority", "definition": {"group_by": ["priority"], "measures": ["count"]}, **body}
    r = await client.post("/api/v1/reports", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()
    return created


def parts(msg: EmailMessage) -> tuple[str, str, list[tuple[str, str]]]:
    text = msg.get_body(("plain",))
    html = msg.get_body(("html",))
    assert text is not None and html is not None
    files = [(a.get_filename() or "", a.get_content()) for a in msg.iter_attachments()]
    return text.get_content(), html.get_content(), files


async def test_off_until_the_server_has_email(client: AsyncClient) -> None:
    world = await make_world()
    saved = await report(client, world.headers)
    status = (await client.get(f"/api/v1/reports/{saved['id']}/email", headers=world.headers)).json()
    assert status == {"available": False, "subscription": None}
    r = await client.put(
        f"/api/v1/reports/{saved['id']}/email", json={"schedule": WEEKLY}, headers=world.headers
    )
    assert r.status_code == 503 and "GLASSHAUS_SMTP_HOST" in r.json()["detail"]
    assert (await send_due()) == {"sent": 0, "failed": 0}


async def test_scheduled_email_runs_with_the_subscribers_access(
    client: AsyncClient, outbox: list[EmailMessage]
) -> None:
    world = await make_world()
    await create_task(client, world, priority="high")
    await create_task(client, world, priority="low")
    saved = await report(
        client,
        world.headers,
        name="<b>Ops</b>\r\nBcc: x@evil.example",
        shared=True,
        definition={"group_by": ["priority"], "measures": ["count", "estimate_hours"]},
    )
    url = f"/api/v1/reports/{saved['id']}/email"
    r = await client.put(url, json={"schedule": WEEKLY, "attach_csv": True}, headers=world.headers)
    assert r.status_code == 200, r.text
    sub = r.json()
    due = datetime.fromisoformat(sub["next_run_at"])
    assert due > datetime.now(due.tzinfo) and due.weekday() == 0 and due.hour == 12  # 08:00 Toronto (EDT)
    assert (
        (await client.get(url, headers=world.headers)).json()["subscription"]["report_name"].startswith("<b>")
    )

    # Someone else subscribes to the shared report; they cannot see the project, so they get zeros.
    outsider = await make_user(world.tenant)
    outsider_headers = auth(await token_for(outsider))
    assert (await client.put(url, json={"schedule": WEEKLY}, headers=outsider_headers)).status_code == 200

    assert await send_due(due - timedelta(minutes=1)) == {"sent": 0, "failed": 0}
    assert await send_due(due + timedelta(seconds=30)) == {"sent": 2, "failed": 0}
    by_to = {m["To"]: m for m in outbox}
    owner_mail = by_to[world.owner.email]
    assert "\n" not in owner_mail["Subject"] and "Bcc" not in owner_mail.keys()  # noqa: SIM118
    text, html, files = parts(owner_mail)
    assert "High | 1" in text and "Total | 2" in text and f"/reports/{saved['id']}" in text
    assert "&lt;b&gt;Ops&lt;/b&gt;" in html and "<b>Ops</b>" not in html
    assert files and files[0][0].endswith(".csv") and files[0][1].startswith("Priority,Tasks,Estimate")
    _, _, outsider_files = parts(by_to[outsider.email])
    assert "Total,0" in outsider_files[0][1]

    # Moved to the following week; a second run in the same minute sends nothing.
    after = (await client.get(url, headers=world.headers)).json()["subscription"]
    assert after["last_sent_at"] is not None and after["last_error"] is None
    assert datetime.fromisoformat(after["next_run_at"]) == due + timedelta(days=7)
    assert await send_due(due + timedelta(seconds=40)) == {"sent": 0, "failed": 0}
    listed = (await client.get("/api/v1/reports/subscriptions", headers=world.headers)).json()
    assert [s["report_id"] for s in listed] == [saved["id"]]

    # Unshared: the outsider can no longer see it, so their email ends. Deactivated people stop too.
    await client.patch(f"/api/v1/reports/{saved['id']}", json={"shared": False}, headers=world.headers)
    async with system_session() as session:
        await session.execute(update(User).where(User.id == world.owner.id).values(is_active=False))
    outbox.clear()
    assert await send_due(due + timedelta(days=7, seconds=30)) == {"sent": 0, "failed": 2}
    assert outbox == []
    async with system_session() as session:
        await session.execute(update(User).where(User.id == world.owner.id).values(is_active=True))
    assert (await client.get("/api/v1/reports/subscriptions", headers=outsider_headers)).json() == []
    assert (await client.get("/api/v1/reports/subscriptions", headers=world.headers)).json() == []


async def test_send_now_unsubscribe_and_scopes(client: AsyncClient, outbox: list[EmailMessage]) -> None:
    world = await make_world()
    saved = await report(client, world.headers, definition={"measures": ["open"]})
    send = f"/api/v1/reports/{saved['id']}/email/send"
    r = await client.post(send, params={"attach_csv": False}, headers=world.headers)
    assert r.status_code == 200 and r.json() == {"sent_to": world.owner.email}
    text, _, files = parts(outbox[-1])
    assert "Open: 0" in text and files == []
    assert (await client.post(send, headers=world.headers)).status_code == 200
    assert (await client.post(send, headers=world.headers)).status_code == 429

    url = f"/api/v1/reports/{saved['id']}/email"
    read_only = auth(await token_for(world.owner, (Scope.READ,)))
    assert (await client.put(url, json={"schedule": WEEKLY}, headers=read_only)).status_code == 403
    bad = {"schedule": {"frequency": "weekly", "hour": 8}}
    assert (await client.put(url, json=bad, headers=world.headers)).status_code == 422
    assert (await client.put(url, json={"schedule": WEEKLY}, headers=world.headers)).status_code == 200
    assert (await client.delete(url, headers=world.headers)).status_code == 204
    assert (await client.delete(url, headers=world.headers)).status_code == 404

    stranger = await make_world()
    assert (await client.get(url, headers=stranger.headers)).status_code == 404
    assert (await client.post(send, headers=stranger.headers)).status_code == 404


def test_smtp_delivery_uses_starttls_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append(f"connect {host}:{port}")

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *exc: object) -> None:
            calls.append("quit")

        def starttls(self, context: object) -> None:
            calls.append("starttls")

        def login(self, user: str, password: str) -> None:
            calls.append(f"login {user} {password}")

        def send_message(self, msg: EmailMessage) -> None:
            calls.append(f"send {msg['To']} {msg['Subject']}")

    settings = get_settings()
    for name, value in {
        "smtp_host": "mail.example.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "reports",
        "smtp_password": SecretStr("pw"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    asyncio.run(mail.send(mail.Mail(to="a@example.com", subject="Hi\nBcc: b@example.com", text="x")))
    assert calls == [
        "connect mail.example.com:587",
        "starttls",
        "login reports pw",
        "send a@example.com Hi Bcc: b@example.com",
        "quit",
    ]
