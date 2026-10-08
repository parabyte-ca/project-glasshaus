"""Executes rules: claim a run (dedupe), apply actions in one transaction, then deliver webhooks.

Rules act as an ``automation`` principal scoped to the rule's project. A run whose database phase
fails is rolled back and logged as failed; failed webhooks are logged and can be retried alone.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from glasshaus.automation import engine, webhooks
from glasshaus.automation.models import AutomationRule, AutomationRun
from glasshaus.automation.schemas import Action, Condition, RunStatus
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import NotFound, ServiceError
from glasshaus.core.rbac import OrgRole
from glasshaus.db import unit_of_work
from glasshaus.logs import get_logger
from glasshaus.projects.models import Project

log = get_logger(__name__)
LOOP_WINDOW = timedelta(minutes=1)
LOOP_LIMIT = 20  # runs per task per minute before the loop guard trips


class _NoMatch(Exception):
    """Conditions did not hold: roll back the claim, record nothing."""


def automation_actor(tenant_id: uuid.UUID, rule_id: uuid.UUID) -> Actor:
    # Project-scoped by construction: every action targets the rule's own project, its tasks,
    # statuses and fields, and assignees are checked against project membership.
    return Actor(
        tenant_id=tenant_id,
        user_id=None,
        org_role=OrgRole.OWNER,
        method="automation",
        client=f"rule:{rule_id}",
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def _apply(
    ctx: ServiceContext, rule: AutomationRule, task_id: uuid.UUID | None, event: dict[str, Any] | None
) -> tuple[engine.Outcome, dict[str, Any]]:
    from glasshaus.tasks import service as tasks

    project = await ctx.session.get(Project, rule.project_id)
    if project is None or project.archived_at is not None:
        raise _NoMatch
    task = None
    if task_id is not None:
        try:
            task = await tasks.get_task(ctx, task_id)
        except NotFound:
            raise _NoMatch from None
        if task.project_id != rule.project_id or task.deleted_at is not None:
            raise _NoMatch
        recent = await ctx.session.scalar(
            select(func.count())
            .select_from(AutomationRun)
            .where(AutomationRun.task_id == task_id, AutomationRun.started_at > _now() - LOOP_WINDOW)
        )
        if (recent or 0) > LOOP_LIMIT:
            raise ServiceError(f"loop guard: more than {LOOP_LIMIT} automation runs on this task in a minute")
    conditions = [Condition.model_validate(c) for c in rule.conditions]
    if task is not None:
        checks = engine.evaluate(conditions, task, _now().date())
        if not all(ok for _, ok in checks):
            raise _NoMatch
    elif conditions:
        raise _NoMatch
    actions = [Action.model_validate(a) for a in rule.actions]
    outcome = await engine.execute(ctx, project, rule.name, actions, task, event=event)
    return outcome, {"task_key": task.key if task else None}


async def fire(
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    task_id: uuid.UUID | None,
    event: dict[str, Any] | None,
    dedupe_key: str,
    trigger_type: str,
) -> uuid.UUID | None:
    """Run a rule once per ``dedupe_key``. Returns the run id, or None if it did not run."""
    run_id = uuid.uuid4()
    started = _now()
    outcome: engine.Outcome | None = None
    try:
        async with unit_of_work(automation_actor(tenant_id, rule_id)) as ctx:
            rule = await ctx.session.get(AutomationRule, rule_id)
            if rule is None or not rule.enabled:
                return None
            claimed = await ctx.session.scalar(
                insert(AutomationRun)
                .values(
                    id=run_id,
                    tenant_id=tenant_id,
                    rule_id=rule_id,
                    project_id=rule.project_id,
                    task_id=task_id,
                    dedupe_key=dedupe_key[:200],
                    trigger_type=trigger_type,
                    status=RunStatus.SUCCESS,
                    results={},
                    context={"event": event},
                    started_at=started,
                )
                .on_conflict_do_nothing(index_elements=["rule_id", "dedupe_key"])
                .returning(AutomationRun.id)
            )
            if claimed is None:
                return None  # already handled (redelivery or a concurrent worker)
            outcome, extra = await _apply(ctx, rule, task_id, event)
            await _finish_db_phase(ctx, rule, run_id, outcome, extra)
    except _NoMatch:
        return None
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the run
        await _record_failure(
            tenant_id, rule_id, run_id, task_id, event, dedupe_key, trigger_type, started, exc
        )
        return run_id
    await _after_commit(tenant_id, rule_id, run_id, outcome)
    return run_id


async def _finish_db_phase(
    ctx: ServiceContext,
    rule: AutomationRule,
    run_id: uuid.UUID,
    outcome: engine.Outcome,
    extra: dict[str, Any],
) -> None:
    pending = [{"url": w.url, "payload": w.payload} for w in outcome.webhooks]
    now = _now()
    run = await ctx.session.get(AutomationRun, run_id)
    assert run is not None
    run.status = RunStatus.SUCCESS
    run.error = None
    run.results = {
        "actions": outcome.actions,
        "webhooks": [],
        "phase": "webhooks" if pending else "done",
        **extra,
    }
    run.context = {**run.context, "pending_webhooks": pending}
    run.finished_at = None if pending else now
    rule.last_run_at = now


async def _after_commit(
    tenant_id: uuid.UUID, rule_id: uuid.UUID, run_id: uuid.UUID, outcome: engine.Outcome | None
) -> None:
    if outcome is None:
        return
    if outcome.notified:
        from glasshaus.realtime import publish_user_signal

        await publish_user_signal(tenant_id, outcome.notified, "notification.created")
    if outcome.webhooks:
        await deliver(tenant_id, rule_id, run_id)


async def _record_failure(
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    run_id: uuid.UUID,
    task_id: uuid.UUID | None,
    event: dict[str, Any] | None,
    dedupe_key: str,
    trigger_type: str,
    started: datetime,
    exc: Exception,
) -> None:
    error = exc.detail if isinstance(exc, ServiceError) else f"{type(exc).__name__}: {exc}"
    if not isinstance(exc, ServiceError):
        log.warning("automation.run_failed", rule=str(rule_id), exc_info=True)
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        project_id = await ctx.session.scalar(
            select(AutomationRule.project_id).where(AutomationRule.id == rule_id)
        )
        if project_id is None:
            return
        await ctx.session.execute(
            insert(AutomationRun)
            .values(
                id=run_id,
                tenant_id=tenant_id,
                rule_id=rule_id,
                project_id=project_id,
                task_id=task_id,
                dedupe_key=dedupe_key[:200],
                trigger_type=trigger_type,
                status=RunStatus.FAILED,
                error=error[:2000],
                results={"phase": "actions"},
                context={"event": event},
                started_at=started,
                finished_at=_now(),
            )
            .on_conflict_do_update(
                index_elements=["rule_id", "dedupe_key"],
                set_={
                    "status": RunStatus.FAILED,
                    "error": error[:2000],
                    "results": {"phase": "actions"},
                    "finished_at": _now(),
                },
            )
        )
        await ctx.session.execute(
            update(AutomationRule).where(AutomationRule.id == rule_id).values(last_run_at=_now())
        )


async def deliver(tenant_id: uuid.UUID, rule_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Send the run's pending webhooks; keep only the failed ones pending (for retry)."""
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        run = await ctx.session.get(AutomationRun, run_id)
        secret = await ctx.session.scalar(
            select(AutomationRule.webhook_secret).where(AutomationRule.id == rule_id)
        )
        pending: list[dict[str, Any]] = list((run.context if run else {}).get("pending_webhooks", []))
    if run is None or not pending:
        return
    results = [await webhooks.send(p["url"], p["payload"], secret=secret) for p in pending]
    failed = [p for p, r in zip(pending, results, strict=True) if not r.ok]
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        run = await ctx.session.get(AutomationRun, run_id)
        if run is None:
            return
        earlier = [w for w in run.results.get("webhooks", []) if w.get("ok")]
        run.results = {
            **run.results,
            "webhooks": earlier + [r.as_dict() for r in results],
            "phase": "webhooks" if failed else "done",
        }
        run.context = {**run.context, "pending_webhooks": failed}
        run.status = RunStatus.FAILED if failed else RunStatus.SUCCESS
        run.error = "; ".join(f"{r.url}: {r.error}" for r in results if not r.ok)[:2000] or None
        run.finished_at = _now()


async def retry(tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Retry a failed run: resend failed webhooks only if the actions succeeded, else rerun the rule."""
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        run = await ctx.session.get(AutomationRun, run_id)
        if run is None:
            raise NotFound("run not found")
        if run.status != RunStatus.FAILED:
            from glasshaus.core.errors import InvalidInput

            raise InvalidInput("only failed runs can be retried")
        run.attempts += 1
        rule_id, task_id, event = run.rule_id, run.task_id, run.context.get("event")
        webhooks_only = run.results.get("phase") == "webhooks"
    if webhooks_only:
        await deliver(tenant_id, rule_id, run_id)
        return
    outcome: engine.Outcome | None = None
    try:
        async with unit_of_work(automation_actor(tenant_id, rule_id)) as ctx:
            rule = await ctx.session.get(AutomationRule, rule_id)
            if rule is None:
                raise NotFound("rule not found")
            outcome, extra = await _apply(ctx, rule, task_id, event)
            await _finish_db_phase(ctx, rule, run_id, outcome, extra)
    except _NoMatch:
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            await ctx.session.execute(
                update(AutomationRun)
                .where(AutomationRun.id == run_id)
                .values(
                    status=RunStatus.SKIPPED,
                    error="conditions no longer match (or the task is gone)",
                    finished_at=_now(),
                )
            )
        return
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the run
        error = exc.detail if isinstance(exc, ServiceError) else f"{type(exc).__name__}: {exc}"
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            await ctx.session.execute(
                update(AutomationRun)
                .where(AutomationRun.id == run_id)
                .values(status=RunStatus.FAILED, error=error[:2000], finished_at=_now())
            )
        return
    await _after_commit(tenant_id, rule_id, run_id, outcome)
