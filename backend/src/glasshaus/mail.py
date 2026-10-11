"""Outgoing email. Off unless GLASSHAUS_SMTP_HOST is set; "memory" keeps messages for tests and demos."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid

from glasshaus.config import get_settings
from glasshaus.core.errors import Unavailable

# Messages "sent" while GLASSHAUS_SMTP_HOST=memory.
OUTBOX: list[EmailMessage] = []


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content: bytes
    maintype: str = "text"
    subtype: str = "csv"


@dataclass(frozen=True, slots=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


def available() -> bool:
    return bool(get_settings().smtp_host)


def _one_line(value: str) -> str:
    """Headers never carry line breaks (header injection)."""
    return " ".join(value.split())


def build(mail: Mail) -> EmailMessage:
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = _one_line(mail.to)
    msg["Subject"] = _one_line(mail.subject)[:200]
    msg["Message-ID"] = make_msgid(domain="glasshaus")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(mail.text)
    if mail.html is not None:
        msg.add_alternative(mail.html, subtype="html")
    for a in mail.attachments:
        msg.add_attachment(a.content, maintype=a.maintype, subtype=a.subtype, filename=_one_line(a.filename))
    return msg


def _deliver(msg: EmailMessage) -> None:
    s = get_settings()
    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if s.smtp_security == "tls":
        smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context)
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
    with smtp:
        if s.smtp_security == "starttls":
            smtp.starttls(context=context)
        if s.smtp_username:
            password = s.smtp_password.get_secret_value() if s.smtp_password else ""
            smtp.login(s.smtp_username, password)
        smtp.send_message(msg)


async def send(mail: Mail) -> None:
    """Send one message. Raises Unavailable when email is off and on any delivery failure."""
    settings = get_settings()
    if not settings.smtp_host:
        raise Unavailable("email is not configured on this server (GLASSHAUS_SMTP_HOST)")
    msg = build(mail)
    if settings.smtp_host == "memory":
        OUTBOX.append(msg)
        return
    try:
        await asyncio.to_thread(_deliver, msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise Unavailable(f"email delivery failed: {type(exc).__name__}") from None
