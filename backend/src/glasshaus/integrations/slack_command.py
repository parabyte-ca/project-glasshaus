"""The /glasshaus Slack command. Answers only the person who asked (ephemeral), with their access.

Slack signs every request; Glasshaus checks the signature and the timestamp, answers "working on
it" at once, then looks the person up by their Slack email (users.info, with the app's bot token),
finds the Glasshaus account with that email and answers as that person with read-only access. People
without a matching active account get a polite "not linked" answer and no data.

Commands: help, my (your open tasks), a task key (WEB-12), report <name>, or a question (answered
by the AI assistant when it is on: from reports if allowed, otherwise by finding tasks).
"""

import hashlib
import hmac
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import func, select

from glasshaus.config import get_settings
from glasshaus.core.context import Actor
from glasshaus.core.errors import InvalidInput, NotFound, ServiceError, Unauthenticated
from glasshaus.core.rbac import Scope
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.integrations.models import Integration
from glasshaus.integrations.service import _secrets_of
from glasshaus.logs import get_logger

log = get_logger(__name__)
SLACK_API = "https://slack.com/api"
MAX_AGE_SECONDS = 300
TASK_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-\d{1,7}$")
HELP = (
    "*/glasshaus* answers only you, with your access.\n"
    "• `/glasshaus my`: your open tasks\n"
    "• `/glasshaus WEB-12`: one task\n"
    "• `/glasshaus report Open work`: run a saved report\n"
    "• `/glasshaus who has the most overdue work?`: ask a question (when the AI assistant is on)"
)


@dataclass(frozen=True)
class Command:
    tenant_id: uuid.UUID
    integration_id: uuid.UUID
    slack_user: str
    text: str
    response_url: str


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _url(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


def verify(signing_secret: str, headers: dict[str, str], body: bytes, now: float | None = None) -> None:
    """Slack request signing (v0): HMAC-SHA256 of 'v0:<timestamp>:<body>', timestamp within 5 minutes."""
    stamp = headers.get("x-slack-request-timestamp", "")
    if not stamp.isdigit() or abs((now or time.time()) - int(stamp)) > MAX_AGE_SECONDS:
        raise Unauthenticated("stale or missing Slack timestamp")
    expected = (
        "v0=" + hmac.new(signing_secret.encode(), f"v0:{stamp}:".encode() + body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected, headers.get("x-slack-signature", "")):
        raise Unauthenticated("invalid Slack signature")


async def accept(integration_id: uuid.UUID, headers: dict[str, str], body: bytes) -> Command | None:
    """Check a slash-command request. Returns the work to do, or None for Slack's SSL check."""
    async with system_session() as session:  # the tenant is not known until the integration is found
        found = await session.scalar(select(Integration).where(Integration.id == integration_id))
        secrets = _secrets_of(found) if found is not None else {}
        usable = found is not None and found.kind == "slack_command" and found.enabled
        tenant_id = found.tenant_id if found is not None else None
    if not usable or tenant_id is None:
        raise NotFound("integration not found")
    verify(secrets.get("signing", ""), headers, body)
    form = {k: v[0] for k, v in parse_qs(body.decode(errors="replace")).items()}
    if form.get("ssl_check") == "1":
        return None
    response_url = form.get("response_url", "")
    parts = urlsplit(response_url)
    if parts.scheme != "https" or parts.hostname != "hooks.slack.com":
        raise InvalidInput("unexpected response_url")
    return Command(
        tenant_id=tenant_id,
        integration_id=integration_id,
        slack_user=form.get("user_id", ""),
        text=form.get("text", "")[:500],
        response_url=response_url,
    )


async def slack_email(token: str, slack_user: str) -> str | None:
    """The person's email from Slack (needs the users:read.email scope)."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{SLACK_API}/users.info",
            params={"user": slack_user},
            headers={"Authorization": f"Bearer {token}"},
        )
    data = r.json() if r.status_code == 200 else {}
    if not data.get("ok"):
        log.warning("slack_command.users_info_failed", error=data.get("error"))
        return None
    email = ((data.get("user") or {}).get("profile") or {}).get("email")
    return str(email) if email else None


async def respond(response_url: str, message: dict[str, Any]) -> None:
    from glasshaus.automation.webhooks import send

    result = await send(
        response_url, {"response_type": "ephemeral", "replace_original": True, **message}, secret=None
    )
    if not result.ok:
        log.warning("slack_command.respond_failed", error=result.error, status=result.status_code)


def _text(text: str, *, link: str | None = None) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if link:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{link}|Open in Glasshaus>"}]}
        )
    return {"text": _clip(re.sub(r"[*_`]", "", text), 150), "blocks": blocks}


def _task_line(key: str, title: str, due: date | None, status: str | None = None) -> str:
    extra = ", ".join(x for x in [status or "", f"due {due}" if due else ""] if x)
    return f"• *{_escape(key)}* {_escape(_clip(title, 90))}" + (f" ({extra})" if extra else "")


async def answer(actor: Actor, text: str) -> dict[str, Any]:
    """Work out the reply for one command, as ``actor`` (read-only)."""
    from glasshaus.projects.models import StatusCategory
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskQuery, TaskSort

    words = text.strip()
    lower = words.lower()
    if lower in ("", "help", "?"):
        return _text(HELP)
    if lower in ("my", "my tasks", "mine"):
        async with unit_of_work(actor) as ctx:
            page = await tasks.list_tasks(
                ctx,
                TaskQuery(
                    assignee_ids=[actor.user_id] if actor.user_id else None,
                    status_categories=[
                        StatusCategory.BACKLOG,
                        StatusCategory.TODO,
                        StatusCategory.IN_PROGRESS,
                    ],
                    sort=TaskSort.DUE,
                    limit=10,
                ),
            )
        if not page.items:
            return _text("You have no open tasks. :tada:")
        lines = [_task_line(t.key, t.title, t.due_date, t.status.name) for t in page.items]
        return _text("*Your open tasks*\n" + "\n".join(lines), link=_url("/"))
    if TASK_KEY.match(words):
        async with unit_of_work(actor) as ctx:
            try:
                task = await tasks.get_task(ctx, await tasks.resolve_ref(ctx, words.upper()))
            except NotFound:
                return _text(f"I can't find {_escape(words.upper())}, or you can't see it.")
        project_key = task.key.rsplit("-", 1)[0]
        return _text(
            _task_line(task.key, task.title, task.due_date, task.status.name).removeprefix("• "),
            link=_url(f"/projects/{project_key}?task={task.id}"),
        )
    if lower.startswith("report "):
        return await _report(actor, words[7:].strip())
    return await _ask(actor, words)


async def _report(actor: Actor, name: str) -> dict[str, Any]:
    from glasshaus.integrations.posts import render_report
    from glasshaus.reports import engine
    from glasshaus.reports import service as reports
    from glasshaus.reports.schemas import ReportDefinition

    async with unit_of_work(actor) as ctx:
        saved = await reports.list_reports(ctx)
        wanted = name.lower()
        match = next((r for r in saved if r.name.lower() == wanted), None) or next(
            (r for r in saved if r.name.lower().startswith(wanted)), None
        )
        if match is None:
            names = ", ".join(r.name for r in saved[:10]) or "none yet"
            return _text(f"No saved report called “{_escape(name)}”. Yours: {_escape(names)}.")
        definition = ReportDefinition.model_validate(match.definition)
        result = await engine.run(ctx, definition)
    message = render_report("slack", match.name, match.id, result)
    return {"text": message["text"], "blocks": message["blocks"]}


async def _ask(actor: Actor, question: str) -> dict[str, Any]:
    from glasshaus.ai import service as ai

    async with unit_of_work(actor) as ctx:
        status = await ai.get_status(ctx)
    features = set(status.features) if status.available and status.enabled else set()
    if "reports" in features:
        reply = await ai.ask_reports(actor, ai.AiReportQuestion(question=question))
        link = _url(f"/reports/{reply.saved_report_id}") if reply.saved_report_id else _url("/reports")
        return _text(f"{_escape(reply.answer)}\n_{_escape(reply.explanation)}_", link=link)
    if "search" in features:
        found = await ai.search(actor, ai.AiSearchRequest(query=question, limit=10))
        if not found.items:
            return _text("No tasks match that.")
        lines = [_task_line(t.key, t.title, t.due_date, t.status.name) for t in found.items]
        return _text("\n".join(lines))
    return _text("I can answer questions when the AI assistant is turned on.\n\n" + HELP)


async def run(command: Command) -> None:
    """Background part: who is asking, the answer, and the reply to Slack. Never raises."""
    try:
        async with unit_of_work(Actor.system(command.tenant_id)) as ctx:
            integration = await ctx.session.get(Integration, command.integration_id)
            token = _secrets_of(integration).get("token", "") if integration is not None else ""
        email = await slack_email(token, command.slack_user) if token and command.slack_user else None
        user = None
        if email:
            async with unit_of_work(Actor.system(command.tenant_id)) as ctx:
                user = await ctx.session.scalar(
                    select(User).where(func.lower(User.email) == email.lower(), User.is_active.is_(True))
                )
        if user is None:
            await respond(
                command.response_url,
                _text(
                    "Your Slack account isn't linked to a Glasshaus account: Glasshaus looks for an "
                    "active account with the same email as your Slack profile."
                ),
            )
            return
        actor = Actor(
            tenant_id=command.tenant_id,
            user_id=user.id,
            org_role=user.org_role,
            method="integration",
            scopes=frozenset({Scope.READ.value}),
            client=f"slack:{command.integration_id}",
        )
        try:
            message = await answer(actor, command.text)
        except ServiceError as exc:
            message = _text(f"Sorry, that didn't work: {_escape(str(exc))}")
        await respond(command.response_url, message)
    except Exception:
        log.exception("slack_command.failed", integration=str(command.integration_id))


async def check_token(token: str) -> str | None:
    """None when the bot token works (auth.test); otherwise Slack's error."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{SLACK_API}/auth.test", headers={"Authorization": f"Bearer {token}"})
        data = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    except httpx.HTTPError as exc:
        return type(exc).__name__
    return None if data.get("ok") else str(data.get("error") or "failed")
