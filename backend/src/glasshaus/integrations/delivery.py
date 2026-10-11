"""Outbound integration delivery: match events, render Slack / Teams / webhook payloads, send with
SSRF protection, and retry with backoff."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.automation.webhooks import Delivery
from glasshaus.collab.models import Comment
from glasshaus.config import get_settings
from glasshaus.core.consumers import handles
from glasshaus.integrations.models import Integration, IntegrationDelivery
from glasshaus.integrations.service import BACKOFF, MAX_ATTEMPTS, OUTBOUND, _secrets_of
from glasshaus.logs import get_logger

log = get_logger(__name__)
MAX_TEXT = 300
SEND_CONCURRENCY = 10
# How long a claimed delivery is left alone before the retry cron may take it over (a crashed sender).
SEND_LEASE = timedelta(minutes=5)


def _is_completion(event: dict[str, Any]) -> bool:
    data = event.get("data") or {}
    changes = data.get("changes") or {}
    status = ((data.get("task") or {}).get("status") or {}).get("category")
    return event["type"] == "task.updated" and "status_id" in changes and status == "done"


def matches(integration: Integration, event: dict[str, Any]) -> bool:
    if not integration.enabled or integration.kind not in OUTBOUND:
        return False
    if integration.project_id and str(integration.project_id) != (event.get("project_id") or ""):
        return False
    wanted = set(integration.events)
    return event["type"] in wanted or ("task.completed" in wanted and _is_completion(event))


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def describe(session: AsyncSession, event: dict[str, Any]) -> dict[str, Any]:
    """Facts for a human message: who, what, which task/project, link. Text fields are user content."""
    from glasshaus.identity.models import User
    from glasshaus.projects.models import Project
    from glasshaus.tasks.models import Task

    base = get_settings().public_url.rstrip("/")
    actor_id = (event.get("actor") or {}).get("user_id")
    actor = None
    if actor_id:
        user = await session.get(User, uuid.UUID(actor_id))
        actor = user.name if user else None
    method = (event.get("actor") or {}).get("method")
    who = actor or {"automation": "An automation", "integration": "An integration"}.get(
        method or "", "Glasshaus"
    )
    data = event.get("data") or {}
    out: dict[str, Any] = {
        "who": who,
        "type": event["type"],
        "url": base,
        "ref": None,
        "title": None,
        "project": None,
    }
    project = None
    if event.get("project_id"):
        project = await session.get(Project, uuid.UUID(event["project_id"]))
        if project:
            out["project"] = project.name
            out["url"] = f"{base}/projects/{project.key}"
    if event.get("aggregate_type") == "task":
        task = await session.get(Task, uuid.UUID(event["aggregate_id"]))
        if task and project:
            out["ref"] = f"{project.key}-{task.number}"
            out["title"] = task.title
            out["url"] = f"{base}/projects/{project.key}?task={out['ref']}"
    t = event["type"]
    subject = f"{out['ref']} {out['title']}" if out["ref"] else out["project"] or ""
    if t == "task.created":
        out["text"] = f"{who} created {subject}"
    elif _is_completion(event):
        out["text"] = f"{who} completed {subject}"
    elif t == "task.updated":
        fields = ", ".join(sorted((data.get("changes") or {}).keys())).replace("_id", "") or "details"
        status = ((data.get("task") or {}).get("status") or {}).get("name")
        out["text"] = f"{who} updated {subject} ({fields})" + (
            f" → {status}" if "status_id" in (data.get("changes") or {}) and status else ""
        )
    elif t == "comment.created":
        out["text"] = f"{who} commented on {subject}"
        comment_id = (data.get("comment") or {}).get("id")
        if comment_id:  # read now: event payloads don't keep comment text
            body = await session.scalar(
                select(Comment.body).where(Comment.id == uuid.UUID(comment_id), Comment.deleted_at.is_(None))
            )
            out["quote"] = body
    elif t == "task.deleted":
        out["text"] = f"{who} deleted {subject or data.get('title', 'a task')}"
    elif t == "task.restored":
        out["text"] = f"{who} restored {subject}"
    elif t == "dependency.created":
        out["text"] = f"{who} added a dependency: {data.get('predecessor_key')} → {data.get('successor_key')}"
    elif t == "time.logged":
        mins = (data.get("entry") or data).get("minutes")
        out["text"] = f"{who} logged {mins} min on {subject}" if mins else f"{who} logged time on {subject}"
    elif t == "project.imported":
        counts = f"{data.get('created', 0)} new and {data.get('updated', 0)} updated tasks"
        out["text"] = f"{who} imported {counts} into {out['project'] or 'a project'}"
    elif t.startswith("project."):
        out["text"] = f"{who} {t.split('.', 1)[1].replace('_', ' ')} project {out['project'] or ''}"
    elif t == "integration.test":
        out["text"] = "✅ Test message from Project Glasshaus: this integration is working."
    else:
        out["text"] = f"{who}: {t} {subject}"
    return out


async def render(session: AsyncSession, integration: Integration, event: dict[str, Any]) -> dict[str, Any]:
    if integration.kind == "webhook":
        return event
    facts = await describe(session, event)
    text = _clip(facts["text"])
    quote = _clip(facts["quote"], 500) if facts.get("quote") else None
    if integration.kind == "slack":
        line = f"{_slack_escape(text)} — <{facts['url']}|Open in Glasshaus>"
        blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": line}}]
        if quote:
            blocks.append(
                {"type": "context", "elements": [{"type": "plain_text", "text": quote, "emoji": False}]}
            )
        return {"text": text, "blocks": blocks, "unfurl_links": False}
    body: list[dict[str, Any]] = [{"type": "TextBlock", "text": text, "wrap": True}]
    if quote:
        body.append({"type": "TextBlock", "text": quote, "wrap": True, "isSubtle": True, "maxLines": 6})
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": [{"type": "Action.OpenUrl", "title": "Open in Glasshaus", "url": facts["url"]}],
    }
    return {
        "type": "message",
        "summary": text,
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
        ],
    }


@dataclass(frozen=True)
class Outgoing:
    """Everything needed to send one delivery without a database connection."""

    delivery_id: uuid.UUID
    integration_id: uuid.UUID
    tenant_id: uuid.UUID
    url: str
    signing: str | None
    payload: dict[str, Any]
    event_type: str


def _outgoing(integration: Integration, delivery: IntegrationDelivery) -> Outgoing:
    values = _secrets_of(integration)
    return Outgoing(
        delivery_id=delivery.id,
        integration_id=integration.id,
        tenant_id=delivery.tenant_id,
        url=values.get("url", ""),
        signing=values.get("signing") if integration.kind == "webhook" else None,
        payload=delivery.payload,
        event_type=delivery.event_type,
    )


async def _send(out: Outgoing) -> Delivery:
    from glasshaus.automation.webhooks import send

    try:
        return await send(out.url, out.payload, secret=out.signing, event=out.event_type)
    except Exception as exc:
        log.warning("integration.delivery_error", integration=str(out.integration_id), exc_info=True)
        return Delivery(url=out.url, ok=False, error=type(exc).__name__)


def _record(integration: Integration, delivery: IntegrationDelivery, result: Delivery) -> bool:
    now = datetime.now(UTC)
    delivery.attempts += 1
    delivery.response_status = result.status_code
    if result.ok:
        delivery.status, delivery.error, delivery.delivered_at, delivery.next_attempt_at = (
            "success",
            None,
            now,
            None,
        )
        integration.last_success_at = now
        return True
    delivery.error = (result.error or "failed")[:500]
    integration.last_error, integration.last_error_at = delivery.error, now
    # Client errors other than rate limits will not succeed on retry.
    permanent = (
        result.status_code is not None and 400 <= result.status_code < 500 and result.status_code != 429
    )
    if permanent or delivery.attempts >= MAX_ATTEMPTS:
        delivery.status, delivery.next_attempt_at = "failed", None
    else:
        delivery.next_attempt_at = now + BACKOFF[min(delivery.attempts - 1, len(BACKOFF) - 1)]
    return False


async def attempt(session: AsyncSession, integration: Integration, delivery: IntegrationDelivery) -> bool:
    """Send one delivery now and record the outcome (the 'send test' button)."""
    return _record(integration, delivery, await _send(_outgoing(integration, delivery)))


async def _send_all(batch: list[Outgoing]) -> int:
    """Send outside any transaction, a few at a time, then record every outcome in one short one."""
    from glasshaus.db import apply_tenant, system_session

    if not batch:
        return 0
    limit = asyncio.Semaphore(SEND_CONCURRENCY)

    async def one(out: Outgoing) -> Delivery:
        async with limit:
            return await _send(out)

    results = await asyncio.gather(*(one(out) for out in batch))
    sent = 0
    async with system_session() as session:
        for out, result in zip(batch, results, strict=True):
            await apply_tenant(session, out.tenant_id)
            delivery = await session.get(IntegrationDelivery, out.delivery_id)
            integration = await session.get(Integration, out.integration_id)
            if delivery is None or integration is None or delivery.status != "pending":
                continue  # deleted meanwhile
            sent += int(_record(integration, delivery, result))
    return sent


@handles("*")
async def fan_out(event: dict[str, Any]) -> None:
    """Queue one delivery per matching integration and try it once now; failures retry on a cron.

    The rows are committed before anything is sent, with their first retry a lease away, so a slow
    endpoint holds no database connection or row lock and a crash mid-send is retried by the cron.
    """
    from glasshaus.db import apply_tenant, system_session

    if event["type"].startswith(("integration.", "sso.", "scim.", "api_token.", "user.password")):
        return
    tenant_id = uuid.UUID(event["tenant_id"])
    batch: list[Outgoing] = []
    async with system_session() as session:
        await apply_tenant(session, tenant_id)
        integrations = [
            i
            for i in (
                await session.scalars(
                    select(Integration).where(
                        Integration.tenant_id == tenant_id, Integration.enabled.is_(True)
                    )
                )
            ).all()
            if matches(i, event)
        ]
        for integration in integrations:
            payload = await render(session, integration, event)
            inserted = await session.scalar(
                insert(IntegrationDelivery)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    integration_id=integration.id,
                    event_id=uuid.UUID(event["id"]),
                    event_type=event["type"],
                    status="pending",
                    attempts=0,
                    payload=payload,
                    next_attempt_at=datetime.now(UTC) + SEND_LEASE,
                )
                .on_conflict_do_nothing()
                .returning(IntegrationDelivery.id)
            )
            if inserted is None:
                continue  # already queued by an earlier delivery of this event
            delivery = await session.get(IntegrationDelivery, inserted)
            assert delivery is not None
            batch.append(_outgoing(integration, delivery))
    await _send_all(batch)


async def retry_due(limit: int = 100) -> int:
    """Worker cron: resend pending deliveries whose backoff has elapsed.

    Due rows are claimed by pushing their next attempt a lease away and committing; the sends then run
    concurrently with no transaction open, and the outcomes are recorded in one short transaction.
    """
    from glasshaus.db import apply_tenant, system_session

    batch: list[Outgoing] = []
    async with system_session() as session:
        now = datetime.now(UTC)
        due = (
            await session.scalars(
                select(IntegrationDelivery)
                .where(
                    IntegrationDelivery.status == "pending",
                    IntegrationDelivery.next_attempt_at <= now,
                )
                .order_by(IntegrationDelivery.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for delivery in due:
            await apply_tenant(session, delivery.tenant_id)
            integration = await session.get(Integration, delivery.integration_id)
            if integration is None or not integration.enabled:
                delivery.status = "failed"
                delivery.error = "integration disabled"
                continue
            delivery.next_attempt_at = now + SEND_LEASE
            batch.append(_outgoing(integration, delivery))
    return await _send_all(batch)
