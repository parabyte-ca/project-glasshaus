"""Scheduled channel posts: a saved report or a project's status, posted to Slack or Teams.

Whoever manages the channel's integration sets a post up. Each post runs with that person's access
at the time it is sent; a channel tied to one project only ever gets that project's numbers. Posts
go through the normal delivery queue, so failures are retried and show in the integration's log.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select

from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import Frequency, ScheduleSpec
from glasshaus.config import get_settings
from glasshaus.core.authz import require_project
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound
from glasshaus.core.rbac import Permission
from glasshaus.core.schemas import Schema
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.insights.schemas import StatusSummary, SummaryTask
from glasshaus.integrations.models import ChannelPost, Integration, IntegrationDelivery
from glasshaus.integrations.service import DeliveryRead, _get
from glasshaus.logs import get_logger
from glasshaus.projects.models import Project
from glasshaus.reports import engine
from glasshaus.reports.models import SavedReport
from glasshaus.reports.schemas import ReportDefinition, ReportResult
from glasshaus.reports.service import _report
from glasshaus.reports.subscriptions import _fmt

log = get_logger(__name__)
CHANNELS = ("slack", "teams")
ROWS = 15
PostKind = Literal["report", "status"]


class ChannelPostCreate(Schema):
    kind: PostKind
    report_id: uuid.UUID | None = Field(None, description="kind=report: the saved report to post.")
    project_id: uuid.UUID | None = Field(
        None, description="kind=status: the project (defaults to the integration's project)."
    )
    schedule: ScheduleSpec


class ChannelPostRead(Schema):
    id: uuid.UUID
    integration_id: uuid.UUID
    kind: PostKind
    report_id: uuid.UUID | None
    project_id: uuid.UUID | None
    title: str = Field(description="The report's name or the project's key and name.")
    schedule: ScheduleSpec
    next_run_at: datetime
    last_sent_at: datetime | None
    last_error: str | None


def _url(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _slack(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _titles(ctx: ServiceContext, posts: list[ChannelPost]) -> dict[uuid.UUID, str]:
    reports = {p.report_id for p in posts if p.report_id}
    projects = {p.project_id for p in posts if p.project_id}
    names: dict[uuid.UUID, str] = {}
    if reports:
        for rid, name in (
            await ctx.session.execute(
                select(SavedReport.id, SavedReport.name).where(SavedReport.id.in_(reports))
            )
        ).all():
            names[rid] = name
    if projects:
        for pid, key, name in (
            await ctx.session.execute(
                select(Project.id, Project.key, Project.name).where(Project.id.in_(projects))
            )
        ).all():
            names[pid] = f"{key} {name}"
    return names


def _read(p: ChannelPost, titles: dict[uuid.UUID, str]) -> ChannelPostRead:
    subject = p.report_id if p.kind == "report" else p.project_id
    return ChannelPostRead(
        id=p.id,
        integration_id=p.integration_id,
        kind=p.kind,
        report_id=p.report_id,
        project_id=p.project_id,
        title=titles.get(subject, "") if subject else "",
        schedule=ScheduleSpec.model_validate(p.schedule),
        next_run_at=p.next_run_at,
        last_sent_at=p.last_sent_at,
        last_error=p.last_error,
    )


async def _channel(ctx: ServiceContext, integration_id: uuid.UUID) -> Integration:
    i = await _get(ctx, integration_id)  # integration managers only
    if i.kind not in CHANNELS:
        raise InvalidInput("scheduled posts go to Slack or Microsoft Teams integrations")
    return i


async def list_posts(ctx: ServiceContext, integration_id: uuid.UUID) -> list[ChannelPostRead]:
    await _channel(ctx, integration_id)
    posts = list(
        (
            await ctx.session.scalars(
                select(ChannelPost)
                .where(ChannelPost.integration_id == integration_id)
                .order_by(ChannelPost.created_at)
            )
        ).all()
    )
    titles = await _titles(ctx, posts)
    return [_read(p, titles) for p in posts]


async def create_post(
    ctx: ServiceContext, integration_id: uuid.UUID, data: ChannelPostCreate
) -> ChannelPostRead:
    i = await _channel(ctx, integration_id)
    if ctx.actor.user_id is None:
        raise InvalidInput("a person sets up channel posts; they run with that person's access")
    post = ChannelPost(
        tenant_id=ctx.tenant_id,
        integration_id=i.id,
        kind=data.kind,
        created_by=ctx.actor.user_id,
        schedule=data.schedule.model_dump(mode="json"),
        next_run_at=next_occurrence(data.schedule, datetime.now(UTC)),
    )
    if data.kind == "report":
        if data.report_id is None:
            raise InvalidInput("choose a saved report")
        await _report(ctx, data.report_id, edit=False)
        post.report_id = data.report_id
    else:
        project_id = data.project_id or i.project_id
        if project_id is None:
            raise InvalidInput("choose a project")
        if i.project_id and project_id != i.project_id:
            raise InvalidInput("this channel belongs to another project")
        await require_project(ctx, project_id, Permission.PROJECT_READ)
        post.project_id = project_id
    ctx.session.add(post)
    await ctx.session.flush()
    return _read(post, await _titles(ctx, [post]))


async def delete_post(ctx: ServiceContext, integration_id: uuid.UUID, post_id: uuid.UUID) -> None:
    await _channel(ctx, integration_id)
    post = await ctx.session.get(ChannelPost, post_id)
    if post is None or post.integration_id != integration_id:
        raise NotFound("post not found")
    await ctx.session.delete(post)
    await ctx.session.flush()


# --- messages ------------------------------------------------------------------------------------


def _cells(result: ReportResult) -> tuple[list[str], list[list[str]], list[str] | None]:
    measures = [c for c in result.columns if c.kind == "measure"]
    dims = [c for c in result.columns if c.kind == "dimension"]
    header = [c.label for c in result.columns]
    rows = [
        [*(_clip(x, 30) for x in r.labels), *(_fmt(v, measures[j]) for j, v in enumerate(r.values))]
        for r in result.rows[:ROWS]
    ]
    totals = (
        [
            "Total",
            *[""] * (len(dims) - 1),
            *(_fmt(v, m) for v, m in zip(result.totals, measures, strict=False)),
        ]
        if dims
        else None
    )
    return header, rows, totals


def _period(result: ReportResult) -> str:
    return f"{result.date_from} to {result.date_to}" if result.date_from and result.date_to else ""


def render_report(kind: str, name: str, report_id: uuid.UUID, result: ReportResult) -> dict[str, Any]:
    link = _url(f"/reports/{report_id}")
    header, rows, totals = _cells(result)
    more = f"Showing {len(rows)} of {result.total_groups} groups." if result.total_groups > len(rows) else ""
    if kind == "slack":
        if totals is None:  # no grouping: one number per measure
            content = "\n".join(
                f"{c.label}: {_fmt(v, c)}"
                for c, v in zip(
                    [c for c in result.columns if c.kind == "measure"], result.totals, strict=False
                )
            )
        else:
            table = [header, *rows, totals]
            widths = [max(len(r[i]) for r in table) for i in range(len(header))]
            dims = len(header) - len([c for c in result.columns if c.kind == "measure"])
            lines = [
                "  ".join(
                    cell.ljust(widths[i]) if i < dims else cell.rjust(widths[i]) for i, cell in enumerate(r)
                )
                for r in table
            ]
            content = "```\n" + "\n".join(lines).replace("`", "'") + "\n```"
        text = "\n".join(
            x for x in [f"*{_slack(_clip(name, 100))}*", _period(result), _slack(content)[:2800], more] if x
        )
        return {
            "text": f"{_clip(name, 100)} report",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{link}|Open in Glasshaus>"}]},
            ],
            "unfurl_links": False,
        }
    measures = [c for c in result.columns if c.kind == "measure"]
    if totals is None:
        facts = [
            {"title": c.label, "value": _fmt(v, c)} for c, v in zip(measures, result.totals, strict=False)
        ]
    else:
        dims = len(header) - len(measures)
        facts = [
            {
                "title": _clip(" · ".join(r[:dims]), 60),
                "value": " · ".join(f"{header[dims + j]}: {v}" for j, v in enumerate(r[dims:])),
            }
            for r in [*rows, totals]
        ]
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": _clip(name, 100), "weight": "Bolder", "size": "Medium", "wrap": True}
    ]
    if _period(result):
        body.append({"type": "TextBlock", "text": _period(result), "isSubtle": True, "spacing": "None"})
    body.append({"type": "FactSet", "facts": facts})
    if more:
        body.append({"type": "TextBlock", "text": more, "isSubtle": True, "wrap": True})
    return _teams(f"{_clip(name, 100)} report", body, link)


def _teams(summary: str, body: list[dict[str, Any]], link: str) -> dict[str, Any]:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": [{"type": "Action.OpenUrl", "title": "Open in Glasshaus", "url": link}],
    }
    return {
        "type": "message",
        "summary": summary,
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
        ],
    }


HEALTH = {"on_track": "On track", "at_risk": "At risk", "off_track": "Off track"}


def _task_line(t: SummaryTask, when: str) -> str:
    date = t.due_date if when == "due" else (t.completed_at.date() if t.completed_at else None)
    return f"{t.key} {_clip(t.title, 80)}" + (f" ({when} {date})" if date else "")


def render_status(kind: str, s: StatusSummary) -> dict[str, Any]:
    link = _url(f"/projects/{s.key}")
    title = f"{s.key} {_clip(s.name, 80)}: {HEALTH.get(s.health.health, s.health.health)}"
    period = f"{s.date_from} to {s.date_to}"
    numbers = (
        f"Open {s.open} · Done {s.done} · Overdue {s.overdue} · {round(s.health.progress * 100)}% complete"
    )
    sections = [
        ("Overdue", [_task_line(t, "due") for t in s.overdue_tasks[:5]]),
        ("Due soon", [_task_line(t, "due") for t in s.due_soon[:5]]),
        ("Completed", [_task_line(t, "done") for t in s.completed[:5]]),
    ]
    if kind == "slack":
        parts = [f"*{_slack(title)}*", period, numbers]
        for heading, lines in sections:
            if lines:
                parts.append(f"*{heading}*\n" + "\n".join(f"• {_slack(x)}" for x in lines))
        return {
            "text": title,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(parts)[:2900]}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{link}|Open in Glasshaus>"}]},
            ],
            "unfurl_links": False,
        }
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": period, "isSubtle": True, "spacing": "None"},
        {"type": "TextBlock", "text": numbers, "wrap": True},
    ]
    for heading, lines in sections:
        if lines:
            body.append({"type": "TextBlock", "text": heading, "weight": "Bolder", "spacing": "Medium"})
            body.append({"type": "TextBlock", "text": "\n".join(f"- {x}" for x in lines), "wrap": True})
    return _teams(title, body, link)


# --- sending -------------------------------------------------------------------------------------

DAYS = {Frequency.DAILY: 1, Frequency.WEEKLY: 7, Frequency.MONTHLY: 30}


async def _compose(tenant_id: uuid.UUID, post_id: uuid.UUID) -> tuple[uuid.UUID, str, dict[str, Any]] | None:
    """Build the message as the person who set the post up. None when the post should end."""
    from glasshaus.insights import service as insights

    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        post = await ctx.session.get(ChannelPost, post_id)
        if post is None:
            return None
        i = await ctx.session.get(Integration, post.integration_id)
        user = await ctx.session.get(User, post.created_by)
        if i is None or user is None or not user.is_active:
            await ctx.session.delete(post)
            return None
        owner = Actor(tenant_id=tenant_id, user_id=user.id, org_role=user.org_role, method="system")
        kind, channel_project = i.kind, i.project_id
        what, report_id, project_id = post.kind, post.report_id, post.project_id
        days = DAYS[ScheduleSpec.model_validate(post.schedule).frequency]
    try:
        async with unit_of_work(owner) as ctx:
            if what == "report":
                assert report_id is not None
                report = await _report(ctx, report_id, edit=False)
                definition = ReportDefinition.model_validate(report.definition)
                if channel_project is not None:  # a project's channel only sees that project
                    filters = definition.filters.model_copy(update={"project_ids": [channel_project]})
                    definition = definition.model_copy(update={"filters": filters})
                payload = render_report(kind, report.name, report_id, await engine.run(ctx, definition))
            else:
                assert project_id is not None
                payload = render_status(kind, await insights.status_summary(ctx, project_id, days=days))
    except NotFound:
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            gone = await ctx.session.get(ChannelPost, post_id)
            if gone is not None:
                await ctx.session.delete(gone)
        log.info("channel_post.dropped", post=str(post_id), reason="no longer visible to its owner")
        return None
    return post_id, f"{what}.posted", payload


async def _deliver(tenant_id: uuid.UUID, post_id: uuid.UUID) -> DeliveryRead | None:
    from glasshaus.integrations.delivery import _outgoing, _send_all

    built = await _compose(tenant_id, post_id)
    if built is None:
        return None
    _, event_type, payload = built
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        post = await ctx.session.get(ChannelPost, post_id)
        if post is None:
            return None
        i = await ctx.session.get(Integration, post.integration_id)
        if i is None or not i.enabled:
            post.last_error = "the integration is turned off"
            return None
        delivery = IntegrationDelivery(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            integration_id=i.id,
            event_id=uuid.uuid4(),
            event_type=event_type,
            status="pending",
            attempts=0,
            payload=payload,
            next_attempt_at=datetime.now(UTC),
        )
        ctx.session.add(delivery)
        await ctx.session.flush()
        outgoing = _outgoing(i, delivery)
        delivery_id = delivery.id
    await _send_all([outgoing])  # outside the transaction; failures retry on the delivery cron
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        sent = await ctx.session.get(IntegrationDelivery, delivery_id)
        post = await ctx.session.get(ChannelPost, post_id)
        if post is not None and sent is not None:
            if sent.status == "success":
                post.last_sent_at, post.last_error = datetime.now(UTC), None
            else:
                post.last_error = (sent.error or "not delivered yet; retrying")[:300]
        return DeliveryRead.model_validate(sent) if sent is not None else None


async def send_now(actor: Actor, integration_id: uuid.UUID, post_id: uuid.UUID) -> DeliveryRead:
    async with unit_of_work(actor) as ctx:
        await _channel(ctx, integration_id)
        post = await ctx.session.get(ChannelPost, post_id)
        if post is None or post.integration_id != integration_id:
            raise NotFound("post not found")
    delivery = await _deliver(actor.tenant_id, post_id)
    if delivery is None:
        raise NotFound(
            "this post can no longer be sent (its report or project is gone, or the integration is off)"
        )
    return delivery


async def send_due(now: datetime | None = None, *, batch: int = 100) -> int:
    """Worker job: send every channel post that is due, then move it to its next occurrence."""
    now = now or datetime.now(UTC)
    due: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with system_session() as session:
        posts = (
            await session.scalars(
                select(ChannelPost)
                .where(ChannelPost.next_run_at <= now)
                .order_by(ChannelPost.next_run_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for post in posts:
            post.next_run_at = next_occurrence(ScheduleSpec.model_validate(post.schedule), now)
            due.append((post.tenant_id, post.id))
    sent = 0
    for tenant_id, post_id in due:
        try:
            delivery = await _deliver(tenant_id, post_id)
            sent += int(delivery is not None and delivery.status == "success")
        except Exception:  # one broken post must not stop the others
            log.exception("channel_post.error", post=str(post_id))
    return sent
