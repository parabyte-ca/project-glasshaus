"""Report emails: people subscribe themselves to a saved report and get it on a schedule.

Each send runs the report as the subscriber, exactly as if they opened it, so an email never shows
more than they could see in the app. Subscriptions end on their own when the subscriber is
deactivated or loses access to the report. The email is built and sent outside any transaction.
"""

import html
import re
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from glasshaus import mail
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import ScheduleSpec
from glasshaus.config import get_settings
from glasshaus.core.authz import require_scope
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, RateLimited, ServiceError, Unavailable
from glasshaus.core.rbac import Permission
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.logs import get_logger
from glasshaus.reports import engine
from glasshaus.reports.models import ReportSubscription, SavedReport
from glasshaus.reports.schemas import (
    Column,
    ReportDefinition,
    ReportEmailStatus,
    ReportResult,
    ReportSubscriptionRead,
    ReportSubscriptionWrite,
)
from glasshaus.reports.service import _report, to_csv

log = get_logger(__name__)

EMAIL_ROWS = 25  # rows in the email body; the CSV attachment carries up to 500
SEND_NOW_PER_MINUTE = 2


def _read(sub: ReportSubscription, name: str) -> ReportSubscriptionRead:
    return ReportSubscriptionRead(
        report_id=sub.report_id,
        report_name=name,
        schedule=ScheduleSpec.model_validate(sub.schedule),
        attach_csv=sub.attach_csv,
        next_run_at=sub.next_run_at,
        last_sent_at=sub.last_sent_at,
        last_error=sub.last_error,
    )


def _user_id(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise InvalidInput("report emails belong to a person; sign in as one")
    return ctx.actor.user_id


async def _mine(ctx: ServiceContext, report_id: uuid.UUID) -> ReportSubscription | None:
    return await ctx.session.scalar(
        select(ReportSubscription).where(
            ReportSubscription.report_id == report_id, ReportSubscription.user_id == _user_id(ctx)
        )
    )


async def email_status(ctx: ServiceContext, report_id: uuid.UUID) -> ReportEmailStatus:
    report = await _report(ctx, report_id, edit=False)
    sub = await _mine(ctx, report_id) if ctx.actor.user_id else None
    return ReportEmailStatus(
        available=mail.available(), subscription=_read(sub, report.name) if sub else None
    )


async def list_subscriptions(ctx: ServiceContext) -> list[ReportSubscriptionRead]:
    rows = (
        await ctx.session.execute(
            select(ReportSubscription, SavedReport.name)
            .join(SavedReport, SavedReport.id == ReportSubscription.report_id)
            .where(ReportSubscription.user_id == _user_id(ctx))
            .order_by(SavedReport.name)
        )
    ).all()
    return [_read(sub, name) for sub, name in rows]


async def subscribe(
    ctx: ServiceContext, report_id: uuid.UUID, data: ReportSubscriptionWrite
) -> ReportSubscriptionRead:
    require_scope(ctx, Permission.TASK_UPDATE)
    if not mail.available():
        raise Unavailable("email is not configured on this server (GLASSHAUS_SMTP_HOST)")
    report = await _report(ctx, report_id, edit=False)
    sub = await _mine(ctx, report_id)
    if sub is None:
        sub = ReportSubscription(tenant_id=ctx.tenant_id, report_id=report_id, user_id=_user_id(ctx))
        ctx.session.add(sub)
    sub.schedule = data.schedule.model_dump(mode="json")
    sub.attach_csv = data.attach_csv
    sub.next_run_at = next_occurrence(data.schedule, datetime.now(UTC))
    sub.last_error = None
    await ctx.session.flush()
    return _read(sub, report.name)


async def unsubscribe(ctx: ServiceContext, report_id: uuid.UUID) -> None:
    require_scope(ctx, Permission.TASK_UPDATE)
    await _report(ctx, report_id, edit=False)
    sub = await _mine(ctx, report_id)
    if sub is None:
        raise NotFound("you are not subscribed to this report")
    await ctx.session.delete(sub)
    await ctx.session.flush()


# --- building the email ------------------------------------------------------------------------


def _fmt(value: float | None, column: Column) -> str:
    if value is None:
        return "-"
    text = f"{value:,.0f}" if column.unit == "count" else f"{value:,.1f}"
    return {"hours": f"{text} h", "days": f"{text} d", "percent": f"{text}%"}.get(column.unit, text)


def build_mail(
    *, to: str, name: str, description: str, report_id: uuid.UUID, result: ReportResult, csv: str | None
) -> mail.Mail:
    """Plain text and HTML (escaped) versions of the report, with the CSV attached when asked."""
    measures = [c for c in result.columns if c.kind == "measure"]
    dims = [c for c in result.columns if c.kind == "dimension"]
    link = f"{get_settings().public_url.rstrip('/')}/reports/{report_id}"
    period = f"{result.date_from} to {result.date_to}" if result.date_from and result.date_to else ""
    rows = [
        [*r.labels, *(_fmt(v, measures[i]) for i, v in enumerate(r.values))] for r in result.rows[:EMAIL_ROWS]
    ]
    totals = [
        *(["Total"] + [""] * (len(dims) - 1) if dims else []),
        *(_fmt(v, m) for v, m in zip(result.totals, measures, strict=False)),
    ]
    header = [c.label for c in result.columns]
    more = (
        f"Showing {len(rows)} of {result.total_groups} groups"
        + ("; the attached CSV has more." if csv else "; open the report for the rest.")
        if result.total_groups > len(rows)
        else ""
    )

    lines = [name, *([description] if description else []), *([period] if period else []), ""]
    if dims:
        lines += [" | ".join(header), *(" | ".join(r) for r in rows), " | ".join(totals)]
    else:
        lines += [f"{m.label}: {_fmt(v, m)}" for v, m in zip(result.totals, measures, strict=False)]
    lines += [
        "",
        *([more] if more else []),
        f"Open in Glasshaus: {link}",
        "",
        "You get this because you asked for it on the report. Change or stop it there.",
    ]

    e = html.escape
    cell = 'style="padding:4px 8px;border-bottom:1px solid #e5e5e5;text-align:{}"'

    def tr(values: list[str], tag: str = "td") -> str:
        return (
            "<tr>"
            + "".join(
                f"<{tag} {cell.format('left' if i < len(dims) else 'right')}>{e(v)}</{tag}>"
                for i, v in enumerate(values)
            )
            + "</tr>"
        )

    if dims:
        table = (
            '<table style="border-collapse:collapse;font-size:14px">'
            f"<thead>{tr(header, 'th')}</thead><tbody>{''.join(tr(r) for r in rows)}</tbody>"
            f'<tfoot style="font-weight:600">{tr(totals)}</tfoot></table>'
        )
    else:
        big = 'style="font-size:24px"'
        table = "".join(
            f'<p style="font-size:14px">{e(m.label)}: <strong {big}>{e(_fmt(v, m))}</strong></p>'
            for v, m in zip(result.totals, measures, strict=False)
        )
    body = (
        '<div style="font-family:Inter,Segoe UI,Arial,sans-serif;color:#212121">'
        f'<h1 style="font-size:18px;margin:0 0 4px">{e(name)}</h1>'
        + (f'<p style="margin:0;color:#525252">{e(description)}</p>' if description else "")
        + (f'<p style="margin:0 0 12px;color:#525252">{e(period)}</p>' if period else "")
        + table
        + (f'<p style="color:#525252">{e(more)}</p>' if more else "")
        + f'<p><a href="{e(link)}" style="color:#1c75bc">Open in Glasshaus</a></p>'
        + '<p style="font-size:12px;color:#525252">You get this because you asked for it on the report. '
        "Change or stop it there.</p></div>"
    )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "report"
    attachments = [mail.Attachment(f"glasshaus-{slug}.csv", csv.encode())] if csv is not None else []
    return mail.Mail(
        to=to,
        subject=f"{name}, {result.generated_at:%Y-%m-%d}",
        text="\n".join(lines),
        html=body,
        attachments=attachments,
    )


# --- sending -----------------------------------------------------------------------------------


async def _compose(actor: Actor, report_id: uuid.UUID, to: str, attach_csv: bool) -> mail.Mail:
    async with unit_of_work(actor) as ctx:
        report = await _report(ctx, report_id, edit=False)
        definition = ReportDefinition.model_validate(report.definition)
        if attach_csv:
            definition = definition.model_copy(update={"limit": 500})
        result = await engine.run(ctx, definition)
        name, description = report.name, report.description
    return build_mail(
        to=to,
        name=name,
        description=description,
        report_id=report_id,
        result=result,
        csv=to_csv(result) if attach_csv else None,
    )


async def _limit_send_now(actor: Actor) -> None:
    from glasshaus.redis_client import get_redis

    key = f"glasshaus:report-mail:rl:{actor.tenant_id}:{actor.user_id}:{int(time.time() // 60)}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 90)
    except Exception:
        log.warning("report_mail.rate_limit_unavailable", exc_info=True)
        return
    if count > SEND_NOW_PER_MINUTE:
        raise RateLimited("too many report emails this minute; try again shortly")


async def send_now(actor: Actor, report_id: uuid.UUID, *, attach_csv: bool = True) -> str:
    """Email the report to the person asking, now. Returns the address it went to."""
    if actor.user_id is None:
        raise InvalidInput("report emails belong to a person; sign in as one")
    if not mail.available():
        raise Unavailable("email is not configured on this server (GLASSHAUS_SMTP_HOST)")
    async with unit_of_work(actor) as ctx:
        require_scope(ctx, Permission.TASK_UPDATE)
        await _report(ctx, report_id, edit=False)
        user = await ctx.session.get(User, actor.user_id)
        assert user is not None
        to = user.email
    await _limit_send_now(actor)
    await mail.send(await _compose(actor, report_id, to, attach_csv))
    return to


async def _finish(tenant_id: uuid.UUID, sub_id: uuid.UUID, *, error: str | None, drop: bool = False) -> None:
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        sub = await ctx.session.get(ReportSubscription, sub_id)
        if sub is None:
            return
        if drop:
            await ctx.session.delete(sub)
        elif error is None:
            sub.last_sent_at, sub.last_error = datetime.now(UTC), None
        else:
            sub.last_error = error[:300]


async def _deliver(
    tenant_id: uuid.UUID, sub_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID, attach_csv: bool
) -> bool:
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        user = await ctx.session.get(User, user_id)
        person = (user.email, user.org_role) if user is not None and user.is_active else None
    if person is None:
        await _finish(tenant_id, sub_id, error=None, drop=True)
        log.info("report_mail.dropped", reason="user inactive", subscription=str(sub_id))
        return False
    actor = Actor(tenant_id=tenant_id, user_id=user_id, org_role=person[1], method="system")
    try:
        message = await _compose(actor, report_id, person[0], attach_csv)
    except NotFound:
        await _finish(tenant_id, sub_id, error=None, drop=True)
        log.info("report_mail.dropped", reason="report gone or not visible", subscription=str(sub_id))
        return False
    try:
        await mail.send(message)
    except ServiceError as exc:
        await _finish(tenant_id, sub_id, error=str(exc))
        log.warning("report_mail.failed", subscription=str(sub_id), error=str(exc))
        return False
    await _finish(tenant_id, sub_id, error=None)
    return True


async def send_due(now: datetime | None = None, *, batch: int = 200) -> dict[str, int]:
    """Worker job: send every report email that is due, then move each to its next occurrence."""
    if not mail.available():
        return {"sent": 0, "failed": 0}
    now = now or datetime.now(UTC)
    due: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, bool]] = []
    async with system_session() as session:
        subs = (
            await session.scalars(
                select(ReportSubscription)
                .where(ReportSubscription.next_run_at <= now)
                .order_by(ReportSubscription.next_run_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for sub in subs:
            # Move on first, so a failing report is retried at its next occurrence, not every minute.
            sub.next_run_at = next_occurrence(ScheduleSpec.model_validate(sub.schedule), now)
            due.append((sub.tenant_id, sub.id, sub.report_id, sub.user_id, sub.attach_csv))
    sent = 0
    for item in due:
        try:
            sent += await _deliver(*item)
        except Exception:  # one broken report must not stop the others
            log.exception("report_mail.error", subscription=str(item[1]))
    return {"sent": sent, "failed": len(due) - sent}
