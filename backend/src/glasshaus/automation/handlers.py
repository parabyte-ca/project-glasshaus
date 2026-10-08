"""Automation triggers: domain events (consumer handlers) and time-based ticks (worker cron)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from glasshaus.automation import runner
from glasshaus.automation.models import AutomationRule, RecurringTask
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import ActionType, RecurringTemplate, ScheduleSpec, Trigger, TriggerType
from glasshaus.core.consumers import Event, handles
from glasshaus.core.context import Actor
from glasshaus.core.rbac import OrgRole
from glasshaus.db import system_session, unit_of_work
from glasshaus.logs import get_logger
from glasshaus.projects.models import StatusCategory

log = get_logger(__name__)
SCHEDULED_TASK_CAP = 500
_TASK_ACTIONS = {a.value for a in ActionType} - {ActionType.WEBHOOK.value, ActionType.NOTIFY.value}

EVENT_TRIGGERS: dict[str, tuple[TriggerType, ...]] = {
    "task.created": (TriggerType.TASK_CREATED,),
    "task.updated": (TriggerType.TASK_UPDATED, TriggerType.STATUS_CHANGED),
    "comment.created": (TriggerType.COMMENT_CREATED,),
}


def trigger_matches(trigger: Trigger, event: Event) -> bool:
    data = event.get("data", {})
    changes: dict[str, Any] = data.get("changes", {})
    match trigger.type:
        case TriggerType.TASK_UPDATED:
            return trigger.field is None or trigger.field in changes
        case TriggerType.STATUS_CHANGED:
            if "status_id" not in changes:
                return False
            status = data.get("task", {}).get("status", {})
            if trigger.to_status_id and str(trigger.to_status_id) != status.get("id"):
                return False
            return not (trigger.to_category and trigger.to_category.value != status.get("category"))
        case _:
            return True


def _caused_by(event: Event) -> tuple[str | None, str | None]:
    actor = event.get("actor", {})
    return actor.get("method"), actor.get("client")


@handles(*EVENT_TRIGGERS)
async def on_event(event: Event) -> None:
    if event.get("aggregate_type") != "task" or not event.get("project_id"):
        return
    tenant_id = uuid.UUID(event["tenant_id"])
    occurred = datetime.fromisoformat(event["occurred_at"])
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        rules = (
            await ctx.session.scalars(
                select(AutomationRule)
                .where(
                    AutomationRule.project_id == uuid.UUID(event["project_id"]),
                    AutomationRule.enabled.is_(True),
                    AutomationRule.trigger_type.in_([t.value for t in EVENT_TRIGGERS[event["type"]]]),
                    # A rule never reacts to events from before it existed (or from the template copy
                    # that created it).
                    AutomationRule.created_at <= occurred,
                )
                .order_by(AutomationRule.created_at)
            )
        ).all()
        candidates = [(r.id, r.run_on_automation, Trigger.model_validate(r.trigger)) for r in rules]
    method, client = _caused_by(event)
    for rule_id, run_on_automation, trigger in candidates:
        if method == "automation" and (not run_on_automation or client == f"rule:{rule_id}"):
            continue  # loop prevention: never react to yourself; others only when opted in
        if not trigger_matches(trigger, event):
            continue
        await runner.fire(
            tenant_id,
            rule_id,
            task_id=uuid.UUID(event["aggregate_id"]),
            event=event,
            dedupe_key=f"event:{event['id']}",
            trigger_type=trigger.type.value,
        )


# --------------------------------------------------------------------------- time-based


async def run_scheduled_rules(now: datetime | None = None) -> int:
    """Fire scheduled rules that are due. Each occurrence fires once (dedupe on its timestamp)."""
    from glasshaus.tasks.models import Task

    now = now or datetime.now(UTC)
    due: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, bool]] = []
    async with system_session() as session:
        rules = (
            await session.scalars(
                select(AutomationRule)
                .where(
                    AutomationRule.trigger_type == TriggerType.SCHEDULED.value,
                    AutomationRule.enabled.is_(True),
                    AutomationRule.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for rule in rules:
            assert rule.next_run_at is not None
            stamp = rule.next_run_at.isoformat()
            trigger = Trigger.model_validate(rule.trigger)
            assert trigger.schedule is not None
            rule.next_run_at = next_occurrence(trigger.schedule, now)
            per_task = bool(rule.conditions) or any(a["type"] in _TASK_ACTIONS for a in rule.actions)
            due.append((rule.tenant_id, rule.id, rule.project_id, stamp, per_task))
    fired = 0
    for tenant_id, rule_id, project_id, stamp, per_task in due:
        if not per_task:
            fired += bool(
                await runner.fire(
                    tenant_id,
                    rule_id,
                    task_id=None,
                    event=None,
                    dedupe_key=f"sched:{stamp}",
                    trigger_type="scheduled",
                )
            )
            continue
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            task_ids = (
                await ctx.session.scalars(
                    select(Task.id)
                    .where(
                        Task.project_id == project_id, Task.deleted_at.is_(None), Task.completed_at.is_(None)
                    )
                    .order_by(Task.number)
                    .limit(SCHEDULED_TASK_CAP)
                )
            ).all()
        for task_id in task_ids:
            fired += bool(
                await runner.fire(
                    tenant_id,
                    rule_id,
                    task_id=task_id,
                    event=None,
                    dedupe_key=f"sched:{stamp}:{task_id}",
                    trigger_type="scheduled",
                )
            )
    return fired


async def run_due_soon_rules(today: date | None = None) -> int:
    """Fire due_soon rules for open tasks due in exactly ``days_before`` days (once per task and due date)."""
    from glasshaus.automation.models import AutomationRun
    from glasshaus.projects.models import ProjectStatus
    from glasshaus.tasks.models import Task

    today = today or datetime.now(UTC).date()
    work: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, date]] = []
    async with system_session() as session:
        rules = (
            await session.scalars(
                select(AutomationRule).where(
                    AutomationRule.trigger_type == TriggerType.DUE_SOON.value,
                    AutomationRule.enabled.is_(True),
                )
            )
        ).all()
        for rule in rules:
            days = Trigger.model_validate(rule.trigger).days_before or 0
            target = today + timedelta(days=days)
            rows = await session.execute(
                select(Task.id)
                .join(ProjectStatus, ProjectStatus.id == Task.status_id)
                .where(
                    Task.project_id == rule.project_id,
                    Task.deleted_at.is_(None),
                    Task.due_date == target,
                    ProjectStatus.category.not_in([StatusCategory.DONE, StatusCategory.CANCELLED]),
                    ~select(AutomationRun.id)
                    .where(
                        AutomationRun.rule_id == rule.id,
                        AutomationRun.dedupe_key == func.concat("due:", Task.id, f":{target}"),
                    )
                    .exists(),
                )
                .limit(SCHEDULED_TASK_CAP)
            )
            work.extend((rule.tenant_id, rule.id, task_id, target) for (task_id,) in rows.all())
    fired = 0
    for tenant_id, rule_id, task_id, target in work:
        fired += bool(
            await runner.fire(
                tenant_id,
                rule_id,
                task_id=task_id,
                event=None,
                dedupe_key=f"due:{task_id}:{target}",
                trigger_type=TriggerType.DUE_SOON.value,
            )
        )
    return fired


async def run_recurring_tasks(now: datetime | None = None) -> int:
    """Create the next instance of every due recurring task (one per occurrence; missed ones collapse)."""
    from zoneinfo import ZoneInfo

    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskCreate

    now = now or datetime.now(UTC)
    async with system_session() as session:
        due = (
            await session.execute(
                select(RecurringTask.id, RecurringTask.tenant_id).where(
                    RecurringTask.enabled.is_(True), RecurringTask.next_run_at <= now
                )
            )
        ).all()
    created = 0
    for recurring_id, tenant_id in due:
        try:
            actor = Actor(
                tenant_id=tenant_id,
                user_id=None,
                org_role=OrgRole.OWNER,
                method="automation",
                client=f"recurring:{recurring_id}",
            )
            async with unit_of_work(actor) as ctx:
                item = await ctx.session.get(
                    RecurringTask, recurring_id, with_for_update={"skip_locked": True}
                )
                if item is None or not item.enabled or item.next_run_at > now:
                    continue  # another worker took it
                spec = ScheduleSpec.model_validate(item.schedule)
                item.next_run_at = next_occurrence(spec, now)
                item.last_run_at = now
                template = RecurringTemplate.model_validate(item.template)
                local_today = now.astimezone(ZoneInfo(spec.timezone)).date()
                task = await tasks.create_task(
                    ctx,
                    TaskCreate(
                        project_id=item.project_id,
                        **template.model_dump(exclude={"due_in_days"}),
                        start_date=local_today if template.due_in_days is not None else None,
                        due_date=(
                            local_today + timedelta(days=template.due_in_days)
                            if template.due_in_days is not None
                            else None
                        ),
                    ),
                )
                item.last_task_id = task.id
                created += 1
        except Exception:
            log.warning("recurring.failed", recurring=str(recurring_id), exc_info=True)
            # Still advance the schedule so one bad template cannot block the queue every minute.
            async with unit_of_work(Actor.system(tenant_id)) as ctx:
                item = await ctx.session.get(RecurringTask, recurring_id)
                if item is not None:
                    item.next_run_at = next_occurrence(ScheduleSpec.model_validate(item.schedule), now)
    return created
