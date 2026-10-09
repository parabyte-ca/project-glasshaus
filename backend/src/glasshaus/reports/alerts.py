"""Report alerts: tell someone when a report's total goes above or below a threshold.

People set alerts for themselves. Each check runs the report as that person, so an alert never
reveals numbers they could not see in the app. A notification (and an email, if asked for and the
server has email) is sent when the alert goes off and again when the number is back within the
threshold, never on every check. Alerts end on their own when the person is deactivated or can no
longer see the report.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from glasshaus import mail
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import ScheduleSpec
from glasshaus.collab.models import NotificationKind
from glasshaus.collab.service import notify_users
from glasshaus.config import get_settings
from glasshaus.core.authz import require_scope
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, ServiceError
from glasshaus.core.rbac import Permission
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import User
from glasshaus.logs import get_logger
from glasshaus.reports import engine
from glasshaus.reports.engine import MEASURE_INFO
from glasshaus.reports.models import ReportAlert, SavedReport
from glasshaus.reports.schemas import ReportAlertRead, ReportAlertWrite, ReportDefinition
from glasshaus.reports.service import _report

log = get_logger(__name__)


def fmt(value: float | None, measure: str) -> str:
    if value is None:
        return "no value"
    unit = MEASURE_INFO.get(measure, ("", "count"))[1]
    text = f"{value:,.0f}" if unit == "count" else f"{value:,.1f}"
    return {"hours": f"{text} h", "days": f"{text} days", "percent": f"{text}%"}.get(unit, text)


def _label(measure: str) -> str:
    return MEASURE_INFO.get(measure, (measure, "count"))[0]


def _read(alert: ReportAlert, name: str) -> ReportAlertRead:
    return ReportAlertRead(
        report_id=alert.report_id,
        report_name=name,
        measure=alert.measure,
        measure_label=_label(alert.measure),
        direction=alert.direction,
        threshold=alert.threshold,
        schedule=ScheduleSpec.model_validate(alert.schedule),
        email=alert.email,
        state=alert.state,
        last_value=alert.last_value,
        last_checked_at=alert.last_checked_at,
        last_error=alert.last_error,
        next_run_at=alert.next_run_at,
    )


def _user_id(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise InvalidInput("report alerts belong to a person; sign in as one")
    return ctx.actor.user_id


async def _mine(ctx: ServiceContext, report_id: uuid.UUID) -> ReportAlert | None:
    return await ctx.session.scalar(
        select(ReportAlert).where(ReportAlert.report_id == report_id, ReportAlert.user_id == _user_id(ctx))
    )


async def get_alert(ctx: ServiceContext, report_id: uuid.UUID) -> ReportAlertRead | None:
    report = await _report(ctx, report_id, edit=False)
    alert = await _mine(ctx, report_id) if ctx.actor.user_id else None
    return _read(alert, report.name) if alert else None


async def list_alerts(ctx: ServiceContext) -> list[ReportAlertRead]:
    rows = (
        await ctx.session.execute(
            select(ReportAlert, SavedReport.name)
            .join(SavedReport, SavedReport.id == ReportAlert.report_id)
            .where(ReportAlert.user_id == _user_id(ctx))
            .order_by(SavedReport.name)
        )
    ).all()
    return [_read(alert, name) for alert, name in rows]


async def set_alert(ctx: ServiceContext, report_id: uuid.UUID, data: ReportAlertWrite) -> ReportAlertRead:
    require_scope(ctx, Permission.TASK_UPDATE)
    report = await _report(ctx, report_id, edit=False)
    measures = ReportDefinition.model_validate(report.definition).measures
    if data.measure not in measures:
        raise InvalidInput(
            f"this report has no '{data.measure}' measure; choose one of: {', '.join(measures)}"
        )
    alert = await _mine(ctx, report_id)
    if alert is None:
        alert = ReportAlert(
            tenant_id=ctx.tenant_id, report_id=report_id, user_id=_user_id(ctx), state="unknown"
        )
        ctx.session.add(alert)
    elif (alert.measure, alert.direction, alert.threshold) != (data.measure, data.direction, data.threshold):
        alert.state, alert.last_value = "unknown", None  # a new condition starts fresh
    alert.measure, alert.direction, alert.threshold = data.measure, data.direction, data.threshold
    alert.schedule = data.schedule.model_dump(mode="json")
    alert.email = data.email
    alert.next_run_at = next_occurrence(data.schedule, datetime.now(UTC))
    alert.last_error = None
    await ctx.session.flush()
    return _read(alert, report.name)


async def delete_alert(ctx: ServiceContext, report_id: uuid.UUID) -> None:
    require_scope(ctx, Permission.TASK_UPDATE)
    await _report(ctx, report_id, edit=False)
    alert = await _mine(ctx, report_id)
    if alert is None:
        raise NotFound("you have no alert on this report")
    await ctx.session.delete(alert)
    await ctx.session.flush()


# --- checking ----------------------------------------------------------------------------------


def _crossed(value: float, direction: str, threshold: float) -> bool:
    return value > threshold if direction == "above" else value < threshold


async def _check(tenant_id: uuid.UUID, alert_id: uuid.UUID) -> str:
    """Check one alert as its owner. Returns the outcome: triggered, cleared, unchanged, error, dropped."""
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        alert = await ctx.session.get(ReportAlert, alert_id)
        if alert is None:
            return "dropped"
        user = await ctx.session.get(User, alert.user_id)
        if user is None or not user.is_active:
            await ctx.session.delete(alert)
            return "dropped"
        owner = Actor(tenant_id=tenant_id, user_id=user.id, org_role=user.org_role, method="system")
        to, report_id = user.email, alert.report_id
        measure, direction, threshold = alert.measure, alert.direction, alert.threshold
        old_state, wants_email = alert.state, alert.email

    value: float | None = None
    error: str | None = None
    try:
        async with unit_of_work(owner) as ctx:
            report = await _report(ctx, report_id, edit=False)
            name = report.name
            definition = ReportDefinition.model_validate(report.definition)
            if measure in definition.measures:
                result = await engine.run(ctx, definition)
                value = result.totals[definition.measures.index(measure)]
            else:
                error = f"the report no longer has the measure '{_label(measure)}'"
    except NotFound:
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            gone = await ctx.session.get(ReportAlert, alert_id)
            if gone is not None:
                await ctx.session.delete(gone)
        log.info("report_alert.dropped", reason="report gone or not visible", alert=str(alert_id))
        return "dropped"

    new_state = old_state
    if error is None and value is not None:
        new_state = "triggered" if _crossed(value, direction, threshold) else "ok"
    outcome = "error" if error else "unchanged"
    title = ""
    if new_state != old_state and not (old_state == "unknown" and new_state == "ok"):
        rule = f"{'above' if direction == 'above' else 'below'} {fmt(threshold, measure)}"
        if new_state == "triggered":
            title, outcome = f"{name}: {_label(measure)} is {fmt(value, measure)}, {rule}", "triggered"
        else:
            title, outcome = (
                f"{name}: {_label(measure)} is back to {fmt(value, measure)} (alert: {rule})",
                "cleared",
            )

    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        alert = await ctx.session.get(ReportAlert, alert_id)
        if alert is None:
            return "dropped"
        alert.last_checked_at, alert.last_error = datetime.now(UTC), error
        if error is None:
            alert.last_value, alert.state = value, new_state
        if title:
            await notify_users(
                ctx,
                [alert.user_id],
                kind=NotificationKind.REPORT_ALERT,
                title=title,
                link=f"/reports/{report_id}",
            )
    if title and wants_email and mail.available():
        link = f"{get_settings().public_url.rstrip('/')}/reports/{report_id}"
        try:
            await mail.send(
                mail.Mail(
                    to=to,
                    subject=title,
                    text=(
                        f"{title}\n\nOpen the report: {link}\n\n"
                        "You set this alert on the report; change or stop it there."
                    ),
                )
            )
        except ServiceError as exc:
            log.warning("report_alert.email_failed", alert=str(alert_id), error=str(exc))
    return outcome


async def check_now(actor: Actor, report_id: uuid.UUID) -> ReportAlertRead:
    """Check your alert on this report right away (notifies on a change, like a scheduled check)."""
    async with unit_of_work(actor) as ctx:
        require_scope(ctx, Permission.TASK_UPDATE)
        await _report(ctx, report_id, edit=False)
        alert = await _mine(ctx, report_id)
        if alert is None:
            raise NotFound("you have no alert on this report")
        alert_id = alert.id
    await _check(actor.tenant_id, alert_id)
    async with unit_of_work(actor) as ctx:
        found = await get_alert(ctx, report_id)
    if found is None:
        raise NotFound("you have no alert on this report")
    return found


async def check_due(now: datetime | None = None, *, batch: int = 200) -> dict[str, int]:
    """Worker job: check every alert that is due, then move each to its next occurrence."""
    now = now or datetime.now(UTC)
    due: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with system_session() as session:
        alerts = (
            await session.scalars(
                select(ReportAlert)
                .where(ReportAlert.next_run_at <= now)
                .order_by(ReportAlert.next_run_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for alert in alerts:
            alert.next_run_at = next_occurrence(ScheduleSpec.model_validate(alert.schedule), now)
            due.append((alert.tenant_id, alert.id))
    counts: dict[str, int] = {}
    for tenant_id, alert_id in due:
        try:
            outcome = await _check(tenant_id, alert_id)
        except Exception:  # one broken report must not stop the others
            log.exception("report_alert.error", alert=str(alert_id))
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
