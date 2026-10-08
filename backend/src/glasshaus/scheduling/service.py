"""Dependencies, critical path, auto-rescheduling, baselines and slip warnings."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from glasshaus.core import events
from glasshaus.core.authz import require_project
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound
from glasshaus.core.rbac import Permission
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.scheduling import cpm
from glasshaus.scheduling.models import Baseline, BaselineTask, TaskDependency
from glasshaus.scheduling.schemas import (
    BaselineCreate,
    BaselineRead,
    BaselineVariance,
    DependencyCreate,
    DependencyRead,
    DependencyResult,
    DependencyUpdate,
    RescheduleResult,
    ScheduledTask,
    ScheduleRead,
    ScheduleWarning,
    TaskDependencies,
    TaskMove,
    TaskVariance,
    WarningKind,
)
from glasshaus.tasks.models import Task

CLOSED = (StatusCategory.DONE, StatusCategory.CANCELLED)


# --------------------------------------------------------------------------- loading


def node_for(task: Task) -> cpm.Node | None:
    start = task.start_date or task.due_date
    finish = task.due_date or task.start_date
    if start is None or finish is None or finish < start:
        return None
    return cpm.Node(task.id, start, finish)


async def _project_tasks(ctx: ServiceContext, project_id: uuid.UUID) -> dict[uuid.UUID, Task]:
    rows = await ctx.session.scalars(
        select(Task).where(Task.project_id == project_id, Task.deleted_at.is_(None)).order_by(Task.number)
    )
    return {t.id: t for t in rows.all()}


async def _project_dependencies(ctx: ServiceContext, project_id: uuid.UUID) -> list[TaskDependency]:
    rows = await ctx.session.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id))
    return list(rows.all())


def _edges(deps: list[TaskDependency], tasks: dict[uuid.UUID, Task]) -> list[cpm.Edge]:
    return [
        cpm.Edge(d.predecessor_id, d.successor_id, d.type, d.lag_days)
        for d in deps
        if d.predecessor_id in tasks and d.successor_id in tasks
    ]


async def _keys(ctx: ServiceContext, project_id: uuid.UUID) -> str:
    key = await ctx.session.scalar(select(Project.key).where(Project.id == project_id))
    return key or "?"


def _dep_read(dep: TaskDependency, tasks: dict[uuid.UUID, Task], key: str) -> DependencyRead:
    pred, succ = tasks[dep.predecessor_id], tasks[dep.successor_id]
    return DependencyRead(
        id=dep.id,
        project_id=dep.project_id,
        predecessor_id=pred.id,
        predecessor_key=f"{key}-{pred.number}",
        predecessor_title=pred.title,
        successor_id=succ.id,
        successor_key=f"{key}-{succ.number}",
        successor_title=succ.title,
        type=dep.type,
        lag_days=dep.lag_days,
        created_at=dep.created_at,
    )


# --------------------------------------------------------------------------- rescheduling


async def _apply_moves(
    ctx: ServiceContext,
    project_id: uuid.UUID,
    tasks: dict[uuid.UUID, Task],
    moved: dict[uuid.UUID, cpm.Node],
    *,
    dry_run: bool,
    reason: str,
) -> list[TaskMove]:
    key = await _keys(ctx, project_id)
    moves: list[TaskMove] = []
    for task_id, node in moved.items():
        task = tasks[task_id]
        new_start = node.start if task.start_date is not None else None
        new_due = node.finish if task.due_date is not None else None
        days = (node.start - (task.start_date or task.due_date)).days  # type: ignore[operator]
        moves.append(
            TaskMove(
                task_id=task.id,
                key=f"{key}-{task.number}",
                start_date=task.start_date,
                due_date=task.due_date,
                new_start_date=new_start,
                new_due_date=new_due,
                days=days,
            )
        )
        if not dry_run:
            before = {"start_date": task.start_date, "due_date": task.due_date}
            task.start_date, task.due_date = new_start, new_due
            events.emit(
                ctx,
                "task.updated",
                "task",
                task.id,
                {
                    "reason": reason,
                    "changes": {
                        k: {"from": v, "to": getattr(task, k)}
                        for k, v in before.items()
                        if v != getattr(task, k)
                    },
                    "task": {
                        "id": str(task.id),
                        "key": f"{key}-{task.number}",
                        "title": task.title,
                        "project_id": str(project_id),
                        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
                    },
                },
                project_id=project_id,
            )
    if moves and not dry_run:
        await ctx.session.flush()
    return sorted(moves, key=lambda m: m.key)


async def propagate_from(ctx: ServiceContext, project: Project, task_ids: set[uuid.UUID]) -> list[TaskMove]:
    """Auto-schedule hook: push successors of changed tasks later when the project opts in."""
    if not project.auto_schedule:
        return []
    tasks = await _project_tasks(ctx, project.id)
    nodes = {tid: n for tid, t in tasks.items() if (n := node_for(t)) is not None}
    deps = await _project_dependencies(ctx, project.id)
    moved = cpm.propagate(nodes, _edges(deps, tasks), changed={t for t in task_ids if t in nodes})
    return await _apply_moves(ctx, project.id, tasks, moved, dry_run=False, reason="auto_schedule")


async def reschedule(ctx: ServiceContext, project_id: uuid.UUID, *, dry_run: bool = True) -> RescheduleResult:
    """Fix every violated dependency by moving successors later (preview by default)."""
    await require_project(ctx, project_id, Permission.TASK_UPDATE)
    tasks = await _project_tasks(ctx, project_id)
    nodes = {tid: n for tid, t in tasks.items() if (n := node_for(t)) is not None}
    deps = await _project_dependencies(ctx, project_id)
    moved = cpm.propagate(nodes, _edges(deps, tasks))
    moves = await _apply_moves(ctx, project_id, tasks, moved, dry_run=dry_run, reason="reschedule")
    return RescheduleResult(executed=not dry_run, moves=moves)


# --------------------------------------------------------------------------- dependencies


async def _resolve(ctx: ServiceContext, ref: str) -> Task:
    from glasshaus.tasks.service import resolve_ref

    task = await ctx.session.get(Task, await resolve_ref(ctx, ref))
    if task is None or task.deleted_at is not None:
        raise NotFound("task not found")
    return task


async def list_dependencies(ctx: ServiceContext, project_id: uuid.UUID) -> list[DependencyRead]:
    await require_project(ctx, project_id, Permission.TASK_READ)
    tasks = await _project_tasks(ctx, project_id)
    key = await _keys(ctx, project_id)
    deps = await _project_dependencies(ctx, project_id)
    return [_dep_read(d, tasks, key) for d in deps if d.predecessor_id in tasks and d.successor_id in tasks]


async def task_dependencies(ctx: ServiceContext, ref: str) -> TaskDependencies:
    task = await _resolve(ctx, ref)
    deps = await list_dependencies(ctx, task.project_id)
    return TaskDependencies(
        predecessors=[d for d in deps if d.successor_id == task.id],
        successors=[d for d in deps if d.predecessor_id == task.id],
    )


async def create_dependency(ctx: ServiceContext, data: DependencyCreate) -> DependencyResult:
    pred, succ = await _resolve(ctx, data.predecessor), await _resolve(ctx, data.successor)
    if pred.project_id != succ.project_id:
        raise InvalidInput("dependencies must link tasks in the same project")
    project = await require_project(ctx, succ.project_id, Permission.TASK_UPDATE)
    tasks = await _project_tasks(ctx, project.id)
    deps = await _project_dependencies(ctx, project.id)
    if cpm.creates_cycle(_edges(deps, tasks), pred.id, succ.id):
        raise InvalidInput("this dependency would create a cycle")
    dep = TaskDependency(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project.id,
        predecessor_id=pred.id,
        successor_id=succ.id,
        type=data.type,
        lag_days=data.lag_days,
    )
    ctx.session.add(dep)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("these tasks are already linked") from exc
    read = _dep_read(dep, tasks, project.key)
    events.emit(ctx, "dependency.created", "task", succ.id, read, project_id=project.id)
    moves = await propagate_from(ctx, project, {pred.id})
    return DependencyResult(dependency=read, rescheduled=moves)


async def _dependency(ctx: ServiceContext, dependency_id: uuid.UUID) -> tuple[TaskDependency, Project]:
    dep = await ctx.session.get(TaskDependency, dependency_id)
    if dep is None:
        raise NotFound("dependency not found")
    project = await require_project(ctx, dep.project_id, Permission.TASK_UPDATE)
    return dep, project


async def update_dependency(
    ctx: ServiceContext, dependency_id: uuid.UUID, data: DependencyUpdate
) -> DependencyResult:
    dep, project = await _dependency(ctx, dependency_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(dep, field, value)
    await ctx.session.flush()
    tasks = await _project_tasks(ctx, project.id)
    read = _dep_read(dep, tasks, project.key)
    events.emit(
        ctx,
        "dependency.updated",
        "task",
        dep.successor_id,
        {"changes": changes, "dependency": read.model_dump(mode="json")},
        project_id=project.id,
    )
    moves = await propagate_from(ctx, project, {dep.predecessor_id})
    return DependencyResult(dependency=read, rescheduled=moves)


async def delete_dependency(ctx: ServiceContext, dependency_id: uuid.UUID) -> None:
    dep, project = await _dependency(ctx, dependency_id)
    await ctx.session.delete(dep)
    events.emit(
        ctx,
        "dependency.deleted",
        "task",
        dep.successor_id,
        {"dependency_id": str(dep.id), "predecessor_id": str(dep.predecessor_id)},
        project_id=project.id,
    )


# --------------------------------------------------------------------------- critical path


async def get_schedule(ctx: ServiceContext, project_id: uuid.UUID) -> ScheduleRead:
    project = await require_project(ctx, project_id, Permission.TASK_READ)
    tasks = await _project_tasks(ctx, project_id)
    nodes = {tid: n for tid, t in tasks.items() if (n := node_for(t)) is not None}
    deps = await _project_dependencies(ctx, project_id)
    result = cpm.critical_path(nodes, _edges(deps, tasks))
    rows = []
    for tid in sorted(nodes, key=lambda t: (result.early_start[t], tasks[t].number)):
        t, n = tasks[tid], nodes[tid]
        slack = result.slack(tid)
        rows.append(
            ScheduledTask(
                task_id=tid,
                key=f"{project.key}-{t.number}",
                title=t.title,
                start_date=n.start,
                due_date=n.finish,
                early_start=result.early_start[tid],
                early_finish=result.early_finish[tid],
                late_start=result.late_start[tid],
                late_finish=result.late_finish[tid],
                slack_days=slack,
                critical=slack <= 0,
            )
        )
    return ScheduleRead(
        project_id=project_id,
        project_start=result.project_start,
        project_finish=result.project_finish,
        tasks=rows,
        critical_path=[r.task_id for r in rows if r.critical],
        unscheduled=[tid for tid in tasks if tid not in nodes],
        dependencies=[
            _dep_read(d, tasks, project.key)
            for d in deps
            if d.predecessor_id in tasks and d.successor_id in tasks
        ],
    )


# --------------------------------------------------------------------------- baselines


async def _baseline_read(ctx: ServiceContext, baseline: Baseline) -> BaselineRead:
    count = await ctx.session.scalar(
        select(func.count()).select_from(BaselineTask).where(BaselineTask.baseline_id == baseline.id)
    )
    return BaselineRead(
        id=baseline.id,
        project_id=baseline.project_id,
        name=baseline.name,
        created_by=baseline.created_by,
        created_at=baseline.created_at,
        task_count=count or 0,
    )


async def list_baselines(ctx: ServiceContext, project_id: uuid.UUID) -> list[BaselineRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    rows = await ctx.session.scalars(
        select(Baseline).where(Baseline.project_id == project_id).order_by(Baseline.created_at.desc())
    )
    return [await _baseline_read(ctx, b) for b in rows.all()]


async def create_baseline(ctx: ServiceContext, project_id: uuid.UUID, data: BaselineCreate) -> BaselineRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    baseline = Baseline(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        name=data.name,
        created_by=ctx.actor.user_id,
    )
    ctx.session.add(baseline)
    await ctx.session.flush()
    for task in (await _project_tasks(ctx, project_id)).values():
        ctx.session.add(
            BaselineTask(
                tenant_id=ctx.tenant_id,
                baseline_id=baseline.id,
                task_id=task.id,
                start_date=task.start_date,
                due_date=task.due_date,
            )
        )
    await ctx.session.flush()
    result = await _baseline_read(ctx, baseline)
    events.emit(
        ctx, "baseline.created", "project", project_id, {"baseline_id": str(baseline.id), "name": data.name}
    )
    return result


async def _baseline(ctx: ServiceContext, baseline_id: uuid.UUID, permission: Permission) -> Baseline:
    baseline = await ctx.session.get(Baseline, baseline_id)
    if baseline is None:
        raise NotFound("baseline not found")
    await require_project(ctx, baseline.project_id, permission)
    return baseline


async def delete_baseline(ctx: ServiceContext, baseline_id: uuid.UUID) -> None:
    baseline = await _baseline(ctx, baseline_id, Permission.PROJECT_UPDATE)
    await ctx.session.execute(delete(BaselineTask).where(BaselineTask.baseline_id == baseline.id))
    await ctx.session.delete(baseline)
    events.emit(ctx, "baseline.deleted", "project", baseline.project_id, {"baseline_id": str(baseline.id)})


def _diff(current: date | None, planned: date | None) -> int | None:
    return (current - planned).days if current and planned else None


async def baseline_variance(ctx: ServiceContext, baseline_id: uuid.UUID) -> BaselineVariance:
    baseline = await _baseline(ctx, baseline_id, Permission.TASK_READ)
    key = await _keys(ctx, baseline.project_id)
    rows = (
        await ctx.session.execute(
            select(BaselineTask, Task)
            .join(Task, Task.id == BaselineTask.task_id)
            .where(BaselineTask.baseline_id == baseline.id, Task.deleted_at.is_(None))
            .order_by(Task.number)
        )
    ).all()
    tasks = [
        TaskVariance(
            task_id=t.id,
            key=f"{key}-{t.number}",
            title=t.title,
            baseline_start=b.start_date,
            baseline_due=b.due_date,
            start_date=t.start_date,
            due_date=t.due_date,
            start_variance_days=_diff(t.start_date, b.start_date),
            finish_variance_days=_diff(t.due_date, b.due_date),
        )
        for b, t in rows
    ]
    planned = [b.due_date for b, _ in rows if b.due_date]
    current = [t.due_date for _, t in rows if t.due_date]
    baseline_finish = max(planned) if planned else None
    current_finish = max(current) if current else None
    return BaselineVariance(
        baseline=await _baseline_read(ctx, baseline),
        tasks=tasks,
        baseline_finish=baseline_finish,
        current_finish=current_finish,
        finish_variance_days=_diff(current_finish, baseline_finish),
    )


# --------------------------------------------------------------------------- warnings


async def schedule_warnings(
    ctx: ServiceContext, project_id: uuid.UUID, *, today: date | None = None
) -> list[ScheduleWarning]:
    project = await require_project(ctx, project_id, Permission.TASK_READ)
    today = today or datetime.now(UTC).date()
    tasks = await _project_tasks(ctx, project_id)
    closed = set(
        (
            await ctx.session.scalars(
                select(ProjectStatus.id).where(
                    ProjectStatus.project_id == project_id, ProjectStatus.category.in_(CLOSED)
                )
            )
        ).all()
    )
    key = project.key
    out: list[ScheduleWarning] = []
    open_tasks = {tid: t for tid, t in tasks.items() if t.status_id not in closed}
    for t in open_tasks.values():
        if t.due_date and t.due_date < today:
            days = (today - t.due_date).days
            out.append(
                ScheduleWarning(
                    kind=WarningKind.OVERDUE,
                    task_id=t.id,
                    key=f"{key}-{t.number}",
                    message=f"{key}-{t.number} is {days} day(s) overdue",
                    days=days,
                )
            )
    nodes = {tid: n for tid, t in tasks.items() if (n := node_for(t)) is not None}
    deps = await _project_dependencies(ctx, project_id)
    for edge, days in cpm.violations(nodes, _edges(deps, tasks)):
        succ, pred = tasks[edge.successor], tasks[edge.predecessor]
        out.append(
            ScheduleWarning(
                kind=WarningKind.DEPENDENCY_VIOLATED,
                task_id=succ.id,
                key=f"{key}-{succ.number}",
                days=days,
                message=(
                    f"{key}-{succ.number} starts {days} day(s) too early for its dependency on "
                    f"{key}-{pred.number}"
                ),
            )
        )
    latest = await ctx.session.scalar(
        select(Baseline)
        .where(Baseline.project_id == project_id)
        .order_by(Baseline.created_at.desc())
        .limit(1)
    )
    if latest is not None:
        variance = await baseline_variance(ctx, latest.id)
        for tv in variance.tasks:
            if tv.task_id in open_tasks and tv.finish_variance_days and tv.finish_variance_days > 0:
                out.append(
                    ScheduleWarning(
                        kind=WarningKind.BEHIND_BASELINE,
                        task_id=tv.task_id,
                        key=tv.key,
                        days=tv.finish_variance_days,
                        message=(
                            f"{tv.key} finishes {tv.finish_variance_days} day(s) later than baseline "
                            f"'{latest.name}'"
                        ),
                    )
                )
        if variance.finish_variance_days and variance.finish_variance_days > 0:
            out.append(
                ScheduleWarning(
                    kind=WarningKind.FINISH_BEHIND_BASELINE,
                    task_id=None,
                    key=None,
                    days=variance.finish_variance_days,
                    message=(
                        f"Project finish is {variance.finish_variance_days} day(s) later than baseline "
                        f"'{latest.name}'"
                    ),
                )
            )
    return sorted(out, key=lambda w: (-w.days, w.key or ""))
