"""Email-to-task: poll an IMAP mailbox (TLS) and turn each unseen message into a task.

The subject becomes the title and the plain-text body the description (untrusted content, never
interpreted). The sender becomes the reporter when they have an account. Messages are marked seen
after the task is created, so a crash can at worst create a duplicate, never lose mail.
"""

import asyncio
import contextlib
import email
import imaplib
import ssl
import uuid
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from typing import Any

from sqlalchemy import func, select

from glasshaus.core.context import Actor
from glasshaus.core.rbac import OrgRole
from glasshaus.integrations.models import Integration
from glasshaus.integrations.service import EmailConfig, _secrets_of
from glasshaus.logs import get_logger

log = get_logger(__name__)
MAX_PER_POLL = 25
MAX_BODY = 20_000


def connect(cfg: EmailConfig, password: str) -> imaplib.IMAP4:
    """Replaced in tests with a fake mailbox."""
    client = imaplib.IMAP4_SSL(cfg.host, cfg.port, ssl_context=ssl.create_default_context(), timeout=20)
    client.login(cfg.username, password)
    return client


def _text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return (
        payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if isinstance(payload, bytes)
        else ""
    )


def _allowed(sender: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    sender = sender.lower()
    return any(sender == a.lower() or (a.startswith("@") and sender.endswith(a.lower())) for a in allowed)


def _fetch(cfg: EmailConfig, password: str) -> list[tuple[bytes, Message]]:
    client = connect(cfg, password)
    try:
        client.select(cfg.folder)
        _, data = client.search(None, "UNSEEN")
        ids: list[bytes] = (data[0] or b"").split()[:MAX_PER_POLL]
        out = []
        for msg_id in ids:
            _, parts = client.fetch(msg_id.decode(), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            out.append((msg_id, email.message_from_bytes(raw)))
        return out
    finally:
        with contextlib.suppress(Exception):  # best-effort logout
            client.logout()


def _mark_seen(cfg: EmailConfig, password: str, ids: list[bytes]) -> None:
    if not ids:
        return
    client = connect(cfg, password)
    try:
        client.select(cfg.folder)
        for msg_id in ids:
            client.store(msg_id.decode(), "+FLAGS", "\\Seen")
    finally:
        with contextlib.suppress(Exception):
            client.logout()


async def check_login(integration: Integration) -> str | None:
    cfg = EmailConfig.model_validate(integration.config["email"])
    password = _secrets_of(integration).get("password", "")

    def run() -> None:
        connect(cfg, password).logout()

    try:
        await asyncio.to_thread(run)
    except Exception as exc:  # noqa: BLE001 - report any connection/login failure to the admin
        return f"{type(exc).__name__}: {exc}"[:500]
    return None


async def poll_integration(integration_id: uuid.UUID) -> int:
    from glasshaus.db import apply_tenant, system_session, unit_of_work
    from glasshaus.identity.models import User
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskCreate

    async with system_session() as session:
        integration = await session.get(Integration, integration_id)
        if integration is None or not integration.enabled or integration.kind != "email":
            return 0
        tenant_id, project_id = integration.tenant_id, integration.project_id
        cfg = EmailConfig.model_validate(integration.config["email"])
        password = _secrets_of(integration).get("password", "")
    try:
        messages = await asyncio.to_thread(_fetch, cfg, password)
    except Exception as exc:  # noqa: BLE001
        async with system_session() as session:
            await apply_tenant(session, tenant_id)
            row = await session.get(Integration, integration_id)
            if row:
                row.last_error, row.last_error_at = f"{type(exc).__name__}: {exc}"[:500], datetime.now(UTC)
        return 0
    created: list[bytes] = []
    actor = Actor(
        tenant_id=tenant_id,
        user_id=None,
        org_role=OrgRole.OWNER,
        method="integration",
        client=f"integration:{integration_id}",
    )
    for msg_id, msg in messages:
        sender = parseaddr(str(msg.get("From", "")))[1]
        if not _allowed(sender, cfg.allowed_senders):
            created.append(msg_id)  # skip, but mark seen so it is not re-read
            continue
        subject = str(make_header(decode_header(str(msg.get("Subject", ""))))).strip() or "(no subject)"
        body = _text(msg)[:MAX_BODY].strip()
        async with unit_of_work(actor) as ctx:
            known = await ctx.session.scalar(
                select(User.name).where(func.lower(User.email) == sender.lower())
            )
            origin = f"From email: {known} <{sender}>" if known else f"From email: {sender}"
            assert project_id is not None
            await tasks.create_task(
                ctx,
                TaskCreate(
                    project_id=project_id,
                    title=subject[:500],
                    description=f"{body}\n\n---\n{origin}" if body else origin,
                ),
            )
        created.append(msg_id)
    await asyncio.to_thread(_mark_seen, cfg, password, created)
    async with system_session() as session:
        await apply_tenant(session, tenant_id)
        row = await session.get(Integration, integration_id)
        if row:
            row.last_success_at = datetime.now(UTC)
            row.last_error = None
    return len(created)


async def poll_all() -> dict[str, Any]:
    """Worker cron: poll every enabled email integration."""
    from glasshaus.db import system_session

    async with system_session() as session:
        ids = (
            await session.scalars(
                select(Integration.id).where(Integration.kind == "email", Integration.enabled.is_(True))
            )
        ).all()
    total = 0
    for integration_id in ids:
        try:
            total += await poll_integration(integration_id)
        except Exception:
            log.warning("integration.email_poll_failed", integration=str(integration_id), exc_info=True)
    return {"mailboxes": len(ids), "tasks": total}
