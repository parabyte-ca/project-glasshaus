"""Email-to-task: poll an IMAP mailbox (TLS) and turn each unseen message into a task.

The subject becomes the title and the plain-text body the description (untrusted content, never
interpreted). The sender becomes the reporter when they have an account. Messages are marked seen
after the task is created, so a crash can at worst create a duplicate, never lose mail.
"""

import asyncio
import contextlib
import email
import imaplib
import ipaddress
import socket
import ssl
import uuid
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from typing import Any

from sqlalchemy import func, select

from glasshaus.automation.webhooks import IP, WebhookRefused, check_address
from glasshaus.config import get_settings
from glasshaus.core.context import Actor
from glasshaus.core.rbac import OrgRole
from glasshaus.integrations.models import Integration
from glasshaus.integrations.service import EmailConfig, _secrets_of
from glasshaus.logs import get_logger

log = get_logger(__name__)
MAX_PER_POLL = 25
MAX_BODY = 20_000


class _PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    """IMAP over TLS to an address checked in advance; the certificate is verified for the host name."""

    def __init__(
        self, host: str, address: str, port: int, ssl_context: ssl.SSLContext, timeout: float
    ) -> None:
        self._address = address
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        sock = socket.create_connection((self._address, self.port), timeout)
        assert self.ssl_context is not None
        wrapped: socket.socket = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        return wrapped


def mail_address(cfg: EmailConfig) -> str:
    """Resolve the IMAP host with the same rules as webhooks: never loopback, link-local or cloud
    metadata; private addresses only with GLASSHAUS_WEBHOOK_ALLOW_PRIVATE (homelab mail servers).
    The connection then goes to the address that was checked (no DNS rebinding)."""
    allow_private = get_settings().webhook_allow_private
    try:
        literal: list[IP] = [ipaddress.ip_address(cfg.host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(cfg.host, cfg.port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise WebhookRefused(f"cannot resolve {cfg.host}") from exc
        literal = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
    if not literal:
        raise WebhookRefused(f"cannot resolve {cfg.host}")
    for ip in literal:
        check_address(ip, allow_private=allow_private)
    return str(literal[0])


def connect(cfg: EmailConfig, password: str) -> imaplib.IMAP4:
    """Replaced in tests with a fake mailbox."""
    client = _PinnedIMAP4SSL(
        cfg.host, mail_address(cfg), cfg.port, ssl_context=ssl.create_default_context(), timeout=20
    )
    client.login(cfg.username, password)
    return client


def describe_error(exc: BaseException) -> str:
    """A short reason for the admin that does not echo server banners or internal details."""
    if isinstance(exc, WebhookRefused):
        return f"refused: {exc}"
    if isinstance(exc, ssl.SSLError):
        return "TLS failed (certificate or protocol); IMAP needs TLS on the configured port"
    if isinstance(exc, imaplib.IMAP4.error):
        return "the mail server refused the sign-in or the folder"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "the mail server did not respond in time"
    if isinstance(exc, OSError):
        return "could not connect to the mail server"
    return "the mailbox could not be read"


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
        log.info("email.check_failed", integration_id=str(integration.id), error=repr(exc)[:300])
        return describe_error(exc)
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
                row.last_error, row.last_error_at = describe_error(exc), datetime.now(UTC)
        log.info("email.poll_failed", integration_id=str(integration_id), error=repr(exc)[:300])
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
