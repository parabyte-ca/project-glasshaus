"""Automation rules, run log and recurring tasks (managing them needs project admin: PROJECT_UPDATE)."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from glasshaus.automation import engine, runner
from glasshaus.automation.models import AutomationRule, AutomationRun, RecurringTask
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import (
    RecurringCreate,
    RecurringRead,
    RecurringUpdate,
    RuleBase,
    RuleCreate,
    RuleRead,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
    RunRead,
    RunStatus,
    TriggerType,
)
from glasshaus.core.authz import project_role, require_project
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound
from glasshaus.core.rbac import Permission, project_role_permissions
from glasshaus.fields.models import CustomField
from glasshaus.identity.models import User
from glasshaus.projects.models import Project, ProjectStatus


def _now() -> datetime:
    return datetime.now(UTC)


async def _can_manage(ctx: ServiceContext, project: Project) -> bool:
    role = await project_role(ctx, project)
    return role is not None and Permission.PROJECT_UPDATE in project_role_permissions(role)


def _read(rule: AutomationRule, *, show_secret: bool) -> RuleRead:
    return RuleRead.model_validate(
        {
            "id": rule.id,
            "project_id": rule.project_id,
            "name": rule.name,
            "enabled": rule.enabled,
            "trigger": rule.trigger,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "run_on_automation": rule.run_on_automation,
            "created_by": rule.created_by,
            "webhook_secret": rule.webhook_secret if show_secret else None,
            "last_run_at": rule.last_run_at,
            "next_run_at": rule.next_run_at,
            "created_at": rule.created_at,
        }
    )


async def _validate_refs(ctx: ServiceContext, project_id: uuid.UUID, rule: RuleBase) -> None:
    """Every status, field and user a rule names must exist (statuses/fields in this project)."""
    status_ids = {a.status_id for a in rule.actions if a.status_id}
    if rule.trigger.to_status_id:
        status_ids.add(rule.trigger.to_status_id)
    field_ids = {a.field_id for a in rule.actions if a.field_id}
    field_ids |= {uuid.UUID(c.field[3:]) for c in rule.conditions if c.field.startswith("cf:")}
    if status_ids:
        found = set(
            (
                await ctx.session.scalars(
                    select(ProjectStatus.id).where(
                        ProjectStatus.project_id == project_id, ProjectStatus.id.in_(status_ids)
                    )
                )
            ).all()
        )
        if missing := status_ids - found:
            raise InvalidInput(f"unknown status {sorted(map(str, missing))[0]} in this project")
    if field_ids:
        found = set(
            (
                await ctx.session.scalars(
                    select(CustomField.id).where(
                        CustomField.project_id == project_id, CustomField.id.in_(field_ids)
                    )
                )
            ).all()
        )
        if missing := field_ids - found:
            raise InvalidInput(f"unknown custom field {sorted(map(str, missing))[0]} in this project")
    user_refs: set[uuid.UUID] = set()
    for action in rule.actions:
        for raw in [action.user or "", *(action.users or [])]:
            if raw and raw not in ("assignee", "reporter", "actor"):
                try:
                    user_refs.add(uuid.UUID(raw))
                except ValueError as exc:
                    raise InvalidInput(f"unknown user reference {raw!r}") from exc
    if user_refs:
        found = set((await ctx.session.scalars(select(User.id).where(User.id.in_(user_refs)))).all())
        if user_refs - found:
            raise InvalidInput("unknown user in actions")


def _next_run(rule: AutomationRule) -> datetime | None:
    from glasshaus.automation.schemas import Trigger

    trigger = Trigger.model_validate(rule.trigger)
    if trigger.type != TriggerType.SCHEDULED or trigger.schedule is None or not rule.enabled:
        return None
    return next_occurrence(trigger.schedule, _now())


async def list_rules(ctx: ServiceContext, project_id: uuid.UUID) -> list[RuleRead]:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    show = await _can_manage(ctx, project)
    rows = await ctx.session.scalars(
        select(AutomationRule)
        .where(AutomationRule.project_id == project_id)
        .order_by(AutomationRule.created_at)
    )
    return [_read(r, show_secret=show) for r in rows.all()]


async def _rule(
    ctx: ServiceContext, rule_id: uuid.UUID, permission: Permission
) -> tuple[AutomationRule, Project]:
    rule = await ctx.session.get(AutomationRule, rule_id)
    if rule is None:
        raise NotFound("rule not found")
    try:
        project = await require_project(ctx, rule.project_id, permission)
    except NotFound:
        raise NotFound("rule not found") from None
    return rule, project


async def get_rule(ctx: ServiceContext, rule_id: uuid.UUID) -> RuleRead:
    rule, project = await _rule(ctx, rule_id, Permission.PROJECT_READ)
    return _read(rule, show_secret=await _can_manage(ctx, project))


async def create_rule(ctx: ServiceContext, project_id: uuid.UUID, data: RuleCreate) -> RuleRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    await _validate_refs(ctx, project_id, data)
    rule = AutomationRule(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        name=data.name,
        enabled=data.enabled,
        trigger_type=data.trigger.type.value,
        trigger=data.trigger.model_dump(mode="json"),
        conditions=[c.model_dump(mode="json") for c in data.conditions],
        actions=[a.model_dump(mode="json", exclude_none=True) for a in data.actions],
        run_on_automation=data.run_on_automation,
        webhook_secret=secrets.token_hex(32),
        created_by=ctx.actor.user_id,
    )
    rule.next_run_at = _next_run(rule)
    ctx.session.add(rule)
    await ctx.session.flush()
    return _read(rule, show_secret=True)


async def update_rule(ctx: ServiceContext, rule_id: uuid.UUID, data: RuleUpdate) -> RuleRead:
    rule, _ = await _rule(ctx, rule_id, Permission.PROJECT_UPDATE)
    merged = RuleBase.model_validate(
        {
            "name": rule.name,
            "enabled": rule.enabled,
            "trigger": rule.trigger,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "run_on_automation": rule.run_on_automation,
            **data.model_dump(exclude_unset=True, mode="json"),
        }
    )
    await _validate_refs(ctx, rule.project_id, merged)
    rule.name = merged.name
    rule.enabled = merged.enabled
    rule.trigger_type = merged.trigger.type.value
    rule.trigger = merged.trigger.model_dump(mode="json")
    rule.conditions = [c.model_dump(mode="json") for c in merged.conditions]
    rule.actions = [a.model_dump(mode="json", exclude_none=True) for a in merged.actions]
    rule.run_on_automation = merged.run_on_automation
    if data.trigger is not None or data.enabled is not None:
        rule.next_run_at = _next_run(rule)
    await ctx.session.flush()
    return _read(rule, show_secret=True)


async def rotate_secret(ctx: ServiceContext, rule_id: uuid.UUID) -> RuleRead:
    rule, _ = await _rule(ctx, rule_id, Permission.PROJECT_UPDATE)
    rule.webhook_secret = secrets.token_hex(32)
    await ctx.session.flush()
    return _read(rule, show_secret=True)


async def delete_rule(ctx: ServiceContext, rule_id: uuid.UUID) -> None:
    rule, _ = await _rule(ctx, rule_id, Permission.PROJECT_UPDATE)
    await ctx.session.delete(rule)
    await ctx.session.flush()


async def test_rule(ctx: ServiceContext, project_id: uuid.UUID, data: RuleTestRequest) -> RuleTestResult:
    """Dry run: evaluate the conditions against a task and list what would happen. Changes nothing."""
    from glasshaus.tasks import service as tasks

    await require_project(ctx, project_id, Permission.PROJECT_READ)
    task = await tasks.get_task(ctx, await tasks.resolve_ref(ctx, data.task))
    if task.project_id != project_id:
        raise InvalidInput("the task must belong to this project")
    checks = engine.evaluate(data.rule.conditions, task, _now().date())
    return RuleTestResult(
        matched=all(ok for _, ok in checks),
        conditions=[
            {
                **c.model_dump(mode="json"),
                "actual": engine.task_value(task, c.field, _now().date()),
                "passed": ok,
            }
            for c, ok in checks
        ],
        planned_actions=[engine.describe(a) for a in data.rule.actions],
    )


# --------------------------------------------------------------------------- runs


def _run_read(run: AutomationRun, rule_name: str) -> RunRead:
    return RunRead(
        id=run.id,
        rule_id=run.rule_id,
        rule_name=rule_name,
        task_id=run.task_id,
        trigger_type=run.trigger_type,
        status=run.status,
        error=run.error,
        results=run.results,
        attempts=run.attempts,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def list_runs(
    ctx: ServiceContext,
    project_id: uuid.UUID,
    *,
    rule_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    limit: int = 50,
) -> list[RunRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    stmt = (
        select(AutomationRun, AutomationRule.name)
        .join(AutomationRule, AutomationRule.id == AutomationRun.rule_id)
        .where(AutomationRun.project_id == project_id)
        .order_by(AutomationRun.started_at.desc(), AutomationRun.id)
        .limit(min(max(limit, 1), 200))
    )
    if rule_id:
        stmt = stmt.where(AutomationRun.rule_id == rule_id)
    if status:
        stmt = stmt.where(AutomationRun.status == status)
    return [_run_read(run, name) for run, name in (await ctx.session.execute(stmt)).all()]


async def retry_run(ctx: ServiceContext, run_id: uuid.UUID) -> RunRead:
    run = await ctx.session.get(AutomationRun, run_id)
    if run is None:
        raise NotFound("run not found")
    try:
        await require_project(ctx, run.project_id, Permission.PROJECT_UPDATE)
    except NotFound:
        raise NotFound("run not found") from None
    if run.status != RunStatus.FAILED:
        raise InvalidInput("only failed runs can be retried")
    await runner.retry(ctx.tenant_id, run_id)  # own transactions; webhooks go out after its commit
    row = (
        await ctx.session.execute(
            select(AutomationRun, AutomationRule.name)
            .join(AutomationRule, AutomationRule.id == AutomationRun.rule_id)
            .where(AutomationRun.id == run_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    return _run_read(row[0], row[1])


# --------------------------------------------------------------------------- recurring tasks


async def _check_template_refs(ctx: ServiceContext, project: Project, data: Any) -> None:
    from glasshaus.fields.service import merge_values
    from glasshaus.tasks.service import _check_assignee

    if data.assignee_id:
        await _check_assignee(ctx, project, data.assignee_id)
    if data.custom_fields:
        await merge_values(ctx, project.id, {}, data.custom_fields)


async def list_recurring(ctx: ServiceContext, project_id: uuid.UUID) -> list[RecurringRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    rows = await ctx.session.scalars(
        select(RecurringTask).where(RecurringTask.project_id == project_id).order_by(RecurringTask.created_at)
    )
    return [RecurringRead.model_validate(r) for r in rows.all()]


async def create_recurring(
    ctx: ServiceContext, project_id: uuid.UUID, data: RecurringCreate
) -> RecurringRead:
    project = await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    await _check_template_refs(ctx, project, data.template)
    item = RecurringTask(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        created_by=ctx.actor.user_id,
        enabled=data.enabled,
        template=data.template.model_dump(mode="json"),
        schedule=data.schedule.model_dump(mode="json"),
        next_run_at=next_occurrence(data.schedule, _now()),
    )
    ctx.session.add(item)
    await ctx.session.flush()
    return RecurringRead.model_validate(item)


async def _recurring(ctx: ServiceContext, recurring_id: uuid.UUID) -> tuple[RecurringTask, Project]:
    item = await ctx.session.get(RecurringTask, recurring_id)
    if item is None:
        raise NotFound("recurring task not found")
    try:
        project = await require_project(ctx, item.project_id, Permission.PROJECT_UPDATE)
    except NotFound:
        raise NotFound("recurring task not found") from None
    return item, project


async def update_recurring(
    ctx: ServiceContext, recurring_id: uuid.UUID, data: RecurringUpdate
) -> RecurringRead:
    from glasshaus.automation.schemas import ScheduleSpec

    item, project = await _recurring(ctx, recurring_id)
    if data.template is not None:
        await _check_template_refs(ctx, project, data.template)
        item.template = data.template.model_dump(mode="json")
    if data.schedule is not None:
        item.schedule = data.schedule.model_dump(mode="json")
    if data.enabled is not None:
        item.enabled = data.enabled
    if data.schedule is not None or data.enabled:
        item.next_run_at = next_occurrence(ScheduleSpec.model_validate(item.schedule), _now())
    await ctx.session.flush()
    return RecurringRead.model_validate(item)


async def delete_recurring(ctx: ServiceContext, recurring_id: uuid.UUID) -> None:
    item, _ = await _recurring(ctx, recurring_id)
    await ctx.session.delete(item)
    await ctx.session.flush()


async def run_rule_now(ctx: ServiceContext, rule_id: uuid.UUID, task_ref: str | None) -> RunRead | None:
    """Fire a rule immediately (optionally against one task), ignoring its trigger. Conditions still
    apply; returns the run, or None when the conditions did not match."""
    from glasshaus.tasks import service as tasks

    rule, _ = await _rule(ctx, rule_id, Permission.PROJECT_UPDATE)
    task_id = None
    if task_ref:
        task = await tasks.get_task(ctx, await tasks.resolve_ref(ctx, task_ref))
        if task.project_id != rule.project_id:
            raise InvalidInput("the task must belong to the rule's project")
        task_id = task.id
    run_id = await runner.fire(
        ctx.tenant_id,
        rule.id,
        task_id=task_id,
        event=None,
        dedupe_key=f"manual:{uuid.uuid4()}",
        trigger_type="manual",
    )
    if run_id is None:
        return None
    row = (
        await ctx.session.execute(
            select(AutomationRun, AutomationRule.name)
            .join(AutomationRule, AutomationRule.id == AutomationRun.rule_id)
            .where(AutomationRun.id == run_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    return _run_read(row[0], row[1])
