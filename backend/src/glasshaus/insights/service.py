"""Workload, project reports, project health and dashboards. Everything is computed from tasks and
time entries the caller can see; nothing here writes task data."""

import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select

from glasshaus.core.authz import require_project, require_scope, require_workspace, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.identity.models import User, WorkspaceMember
from glasshaus.insights import calc
from glasshaus.insights.models import Dashboard
from glasshaus.insights.schemas import (
    AssigneeLoad,
    Bucket,
    BurnupPoint,
    DashboardCreate,
    DashboardRead,
    DashboardUpdate,
    ProjectHealth,
    ProjectReport,
    StatusCount,
    StatusSummary,
    SummaryTask,
    ThroughputPoint,
    TimeSummary,
    Workload,
    WorkloadBucket,
    WorkloadUser,
)
from glasshaus.projects.models import Project, ProjectMember, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Task
from glasshaus.timetracking.models import TimeEntry

CLOSED = (StatusCategory.DONE, StatusCategory.CANCELLED)
MAX_RANGE_DAYS = 366


def _today() -> date:
    return datetime.now(UTC).date()


def _check_range(start: date, end: date) -> None:
    if start > end:
        raise InvalidInput("date_from must be on or before date_to")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise InvalidInput(f"ranges are limited to {MAX_RANGE_DAYS} days")


# --------------------------------------------------------------------------- workload


async def workload(
    ctx: ServiceContext,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    bucket: Bucket = "week",
) -> Workload:
    """Planned remaining work (estimate - logged, spread over each task's dates) against capacity."""
    if ctx.actor.org_role == OrgRole.GUEST:
        raise PermissionDenied("guests cannot view workload")
    start = date_from or calc.bucket_start(_today(), "week")
    end = date_to or start + timedelta(days=27)
    _check_range(start, end)
    scope = [visible_projects_clause(ctx), Project.archived_at.is_(None)]
    if project_id:
        await require_project(ctx, project_id, Permission.PROJECT_READ)
        scope.append(Project.id == project_id)
    if workspace_id:
        await require_workspace(ctx, workspace_id)
        scope.append(Project.workspace_id == workspace_id)

    open_tasks = (
        (
            await ctx.session.execute(
                select(Task)
                .join(Project, Project.id == Task.project_id)
                .join(ProjectStatus, ProjectStatus.id == Task.status_id)
                .where(
                    *scope,
                    Task.deleted_at.is_(None),
                    Task.assignee_id.is_not(None),
                    ProjectStatus.category.not_in(CLOSED),
                )
            )
        )
        .scalars()
        .all()
    )
    logged_by_task = dict(
        (
            await ctx.session.execute(
                select(TimeEntry.task_id, func.sum(TimeEntry.minutes))
                .where(TimeEntry.task_id.in_([t.id for t in open_tasks]))
                .group_by(TimeEntry.task_id)
            )
        ).all()
    )
    user_ids = {t.assignee_id for t in open_tasks if t.assignee_id}
    if project_id:
        project = await ctx.session.get(Project, project_id)
        assert project is not None
        user_ids |= set(
            (
                await ctx.session.scalars(
                    select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
                )
            ).all()
        )
        user_ids |= set(
            (
                await ctx.session.scalars(
                    select(WorkspaceMember.user_id).where(
                        WorkspaceMember.workspace_id == project.workspace_id
                    )
                )
            ).all()
        )
    elif workspace_id:
        user_ids |= set(
            (
                await ctx.session.scalars(
                    select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
                )
            ).all()
        )
    users = (
        (
            await ctx.session.scalars(
                select(User)
                .where(User.id.in_(user_ids), User.is_active.is_(True))
                .order_by(func.lower(User.name))
            )
        ).all()
        if user_ids
        else []
    )
    logged_rows = (
        await ctx.session.execute(
            select(TimeEntry.user_id, TimeEntry.spent_on, func.sum(TimeEntry.minutes))
            .join(Project, Project.id == TimeEntry.project_id)
            .where(
                *scope,
                TimeEntry.spent_on >= start,
                TimeEntry.spent_on <= end,
                TimeEntry.user_id.in_(user_ids),
            )
            .group_by(TimeEntry.user_id, TimeEntry.spent_on)
        )
    ).all()
    logged: dict[tuple[uuid.UUID, date], int] = defaultdict(int)
    for uid, day, minutes in logged_rows:
        logged[(uid, calc.bucket_start(day, bucket))] += int(minutes or 0)

    starts = calc.buckets(start, end, bucket)
    out: list[WorkloadUser] = []
    tasks_by_user: dict[uuid.UUID, list[Task]] = defaultdict(list)
    for t in open_tasks:
        assert t.assignee_id is not None
        tasks_by_user[t.assignee_id].append(t)
    for user in users:
        planned: dict[date, int] = defaultdict(int)
        unscheduled = overdue = unestimated = 0
        for t in tasks_by_user.get(user.id, []):
            if not t.estimate_minutes:
                unestimated += 1
                continue
            remaining = max(t.estimate_minutes - int(logged_by_task.get(t.id) or 0), 0)
            if t.start_date is None and t.due_date is None:
                unscheduled += remaining
                continue
            if (t.due_date or t.start_date) < start:  # type: ignore[operator]
                overdue += remaining
                continue
            for day, minutes in calc.spread(remaining, t.start_date, t.due_date, user.working_days).items():
                if start <= day <= end:
                    planned[calc.bucket_start(day, bucket)] += minutes
        rows = []
        for b in starts:
            b_end = min(b + timedelta(days=6 if bucket == "week" else 0), end)
            rows.append(
                WorkloadBucket(
                    start=b,
                    capacity=calc.capacity(max(b, start), b_end, user.capacity_minutes, user.working_days),
                    planned=planned.get(b, 0),
                    logged=logged.get((user.id, b), 0),
                )
            )
        cap = sum(r.capacity for r in rows)
        plan = sum(r.planned for r in rows)
        out.append(
            WorkloadUser(
                user_id=user.id,
                name=user.name,
                capacity_minutes=user.capacity_minutes,
                working_days=user.working_days,
                buckets=rows,
                capacity_total=cap,
                planned_total=plan,
                logged_total=sum(r.logged for r in rows),
                utilization=round(plan / cap, 3) if cap else None,
                overloaded_buckets=sum(1 for r in rows if r.planned > r.capacity),
                open_tasks=len(tasks_by_user.get(user.id, [])),
                unestimated_tasks=unestimated,
                unscheduled_minutes=unscheduled,
                overdue_minutes=overdue,
            )
        )
    return Workload(date_from=start, date_to=end, bucket=bucket, buckets=starts, users=out)


# --------------------------------------------------------------------------- project report


async def _project_rows(ctx: ServiceContext, project_id: uuid.UUID) -> list[tuple[Task, ProjectStatus]]:
    return [
        (t, s)
        for t, s in (
            await ctx.session.execute(
                select(Task, ProjectStatus)
                .join(ProjectStatus, ProjectStatus.id == Task.status_id)
                .where(Task.project_id == project_id)
            )
        ).all()
    ]


async def project_report(
    ctx: ServiceContext, project_id: uuid.UUID, *, date_from: date | None = None, date_to: date | None = None
) -> ProjectReport:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    end = date_to or _today()
    start = date_from or end - timedelta(days=29)
    _check_range(start, end)
    rows = await _project_rows(ctx, project_id)
    live = [(t, s) for t, s in rows if t.deleted_at is None]
    statuses = (
        await ctx.session.scalars(
            select(ProjectStatus)
            .where(ProjectStatus.project_id == project_id)
            .order_by(ProjectStatus.position)
        )
    ).all()
    counts = Counter(s.id for _, s in live)
    open_rows = [(t, s) for t, s in live if s.category not in CLOSED]
    today = _today()
    logged_totals = dict(
        (
            await ctx.session.execute(
                select(TimeEntry.task_id, func.sum(TimeEntry.minutes))
                .where(TimeEntry.project_id == project_id)
                .group_by(TimeEntry.task_id)
            )
        ).all()
    )
    assignees: dict[uuid.UUID | None, list[int]] = defaultdict(lambda: [0, 0])
    for t, _ in open_rows:
        load = assignees[t.assignee_id]
        load[0] += 1
        load[1] += max((t.estimate_minutes or 0) - int(logged_totals.get(t.id) or 0), 0)

    facts = [
        calc.TaskFacts(
            created=t.created_at.date(),
            completed=t.completed_at.date() if t.completed_at and s.category == StatusCategory.DONE else None,
            deleted=t.deleted_at.date() if t.deleted_at else None,
            cancelled=s.category == StatusCategory.CANCELLED,
        )
        for t, s in rows
    ]
    completed = [
        t
        for t, s in live
        if s.category == StatusCategory.DONE and t.completed_at and start <= t.completed_at.date() <= end
    ]
    weekly = Counter(calc.bucket_start(t.completed_at.date(), "week") for t in completed if t.completed_at)
    lead = [(t.completed_at - t.created_at).total_seconds() / 86400 for t in completed if t.completed_at]
    logged_in_range = await ctx.session.scalar(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.project_id == project_id, TimeEntry.spent_on >= start, TimeEntry.spent_on <= end
        )
    )
    return ProjectReport(
        project_id=project_id,
        date_from=start,
        date_to=end,
        total=len(live),
        open=len(open_rows),
        done=sum(1 for _, s in live if s.category == StatusCategory.DONE),
        overdue=sum(1 for t, _ in open_rows if t.due_date and t.due_date < today),
        by_status=[
            StatusCount(
                status_id=s.id, name=s.name, category=s.category, color=s.color, count=counts.get(s.id, 0)
            )
            for s in statuses
        ],
        by_assignee=[
            AssigneeLoad(user_id=uid, open_tasks=v[0], remaining_minutes=v[1])
            for uid, v in sorted(assignees.items(), key=lambda kv: -kv[1][0])
        ],
        by_priority=dict(Counter(t.priority.value for t, _ in open_rows)),
        burnup=[BurnupPoint(day=d, scope=sc, done=dn) for d, sc, dn in calc.burnup(facts, start, end)],
        throughput=[
            ThroughputPoint(week=w, completed=weekly.get(w, 0)) for w in calc.buckets(start, end, "week")
        ],
        lead_time_days=TimeSummary(
            **{k: (round(v, 1) if v is not None else None) for k, v in calc.summary(lead).items()}
        ),
        estimate_minutes=sum(t.estimate_minutes or 0 for t in completed),
        actual_minutes=sum(int(logged_totals.get(t.id) or 0) for t in completed),
        logged_minutes=int(logged_in_range or 0),
    )


async def project_health(ctx: ServiceContext, project: Project) -> ProjectHealth:
    """Caller has checked that the project is visible."""
    from glasshaus.scheduling import service as scheduling
    from glasshaus.scheduling.models import Baseline

    rows = [(t, s) for t, s in await _project_rows(ctx, project.id) if t.deleted_at is None]
    counted = [(t, s) for t, s in rows if s.category != StatusCategory.CANCELLED]
    done = sum(1 for _, s in counted if s.category == StatusCategory.DONE)
    open_rows = [(t, s) for t, s in counted if s.category not in CLOSED]
    today = _today()
    overdue = sum(1 for t, _ in open_rows if t.due_date and t.due_date < today)
    finish = max((t.due_date for t, _ in open_rows if t.due_date), default=None)
    slip = 0
    baseline_id = await ctx.session.scalar(
        select(Baseline.id)
        .where(Baseline.project_id == project.id)
        .order_by(Baseline.created_at.desc())
        .limit(1)
    )
    if baseline_id:
        variance = await scheduling.baseline_variance(ctx, baseline_id)
        slip = max(variance.finish_variance_days or 0, 0)
    logged = await ctx.session.scalar(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(TimeEntry.project_id == project.id)
    )
    return ProjectHealth(
        project_id=project.id,
        key=project.key,
        name=project.name,
        total=len(counted),
        done=done,
        progress=round(done / len(counted), 3) if counted else 0.0,
        overdue=overdue,
        finish=finish,
        slip_days=slip,
        logged_minutes=int(logged or 0),
        health=calc.health(len(counted), done, overdue, slip),
    )


async def get_project_health(ctx: ServiceContext, project_id: uuid.UUID) -> ProjectHealth:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    return await project_health(ctx, project)


async def export_tasks_csv(ctx: ServiceContext, project_id: uuid.UUID) -> str:
    """Every live task with status, people, dates, estimate vs logged, tags and custom fields."""
    from glasshaus.fields.models import CustomField

    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    rows = [(t, s) for t, s in await _project_rows(ctx, project_id) if t.deleted_at is None]
    rows.sort(key=lambda r: r[0].number)
    fields = (
        await ctx.session.scalars(
            select(CustomField).where(CustomField.project_id == project_id).order_by(CustomField.position)
        )
    ).all()
    people = dict((await ctx.session.execute(select(User.id, User.email))).all())
    logged = dict(
        (
            await ctx.session.execute(
                select(TimeEntry.task_id, func.sum(TimeEntry.minutes))
                .where(TimeEntry.project_id == project_id)
                .group_by(TimeEntry.task_id)
            )
        ).all()
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "key", "title", "status", "category", "priority", "assignee", "reporter", "parent", "start_date",
            "due_date", "estimate_minutes", "logged_minutes", "tags", "created_at", "completed_at",
            *[f.name for f in fields],
        ]
    )  # fmt: skip
    numbers = {t.id: t.number for t, _ in rows}
    for t, s in rows:
        writer.writerow(
            [
                f"{project.key}-{t.number}",
                _safe(t.title),
                s.name,
                s.category.value,
                t.priority.value,
                people.get(t.assignee_id, "") if t.assignee_id else "",
                people.get(t.reporter_id, "") if t.reporter_id else "",
                f"{project.key}-{numbers[t.parent_id]}" if t.parent_id in numbers else "",
                t.start_date.isoformat() if t.start_date else "",
                t.due_date.isoformat() if t.due_date else "",
                t.estimate_minutes or "",
                int(logged.get(t.id) or 0),
                " ".join(t.tags),
                t.created_at.isoformat(),
                t.completed_at.isoformat() if t.completed_at else "",
                *[_cell(t.custom_fields.get(str(f.id)), f) for f in fields],
            ]
        )
    return out.getvalue()


def _cell(value: object, field: object) -> str:
    options = {o["id"]: o["label"] for o in getattr(field, "options", [])}
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(_safe(str(options.get(v, v))) for v in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _safe(str(options.get(value, value)) if isinstance(value, str) else str(value))


def _safe(value: str) -> str:
    """Neutralize spreadsheet formulas (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


# --------------------------------------------------------------------------- dashboards


def _dash_read(d: Dashboard) -> DashboardRead:
    return DashboardRead.model_validate(d)


async def list_dashboards(ctx: ServiceContext) -> list[DashboardRead]:
    clause = Dashboard.owner_id == ctx.actor.user_id
    if ctx.actor.org_role != OrgRole.GUEST:
        clause = or_(clause, Dashboard.shared.is_(True))
    rows = await ctx.session.scalars(select(Dashboard).where(clause).order_by(func.lower(Dashboard.name)))
    return [_dash_read(d) for d in rows.all()]


async def _dashboard(ctx: ServiceContext, dashboard_id: uuid.UUID, *, edit: bool) -> Dashboard:
    if edit:
        require_scope(ctx, Permission.TASK_UPDATE)
    d = await ctx.session.get(Dashboard, dashboard_id)
    mine = d is not None and d.owner_id is not None and d.owner_id == ctx.actor.user_id
    visible = d is not None and (mine or (d.shared and ctx.actor.org_role != OrgRole.GUEST))
    if d is None or not visible:
        raise NotFound("dashboard not found")
    if edit and not (mine or ctx.actor.is_org_admin):
        raise PermissionDenied("only the owner or an organization admin can change this dashboard")
    return d


async def get_dashboard(ctx: ServiceContext, dashboard_id: uuid.UUID) -> DashboardRead:
    return _dash_read(await _dashboard(ctx, dashboard_id, edit=False))


async def create_dashboard(ctx: ServiceContext, data: DashboardCreate) -> DashboardRead:
    require_scope(ctx, Permission.TASK_UPDATE)
    if ctx.actor.user_id is None:
        raise PermissionDenied("dashboards belong to people")
    if data.shared and ctx.actor.org_role == OrgRole.GUEST:
        raise PermissionDenied("guests cannot share dashboards")
    _unique_ids(data.widgets)
    d = Dashboard(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        owner_id=ctx.actor.user_id,
        name=data.name,
        shared=data.shared,
        widgets=[w.model_dump(mode="json") for w in data.widgets],
    )
    ctx.session.add(d)
    await ctx.session.flush()
    return _dash_read(d)


async def update_dashboard(
    ctx: ServiceContext, dashboard_id: uuid.UUID, data: DashboardUpdate
) -> DashboardRead:
    d = await _dashboard(ctx, dashboard_id, edit=True)
    if data.name is not None:
        d.name = data.name
    if data.shared is not None:
        if data.shared and ctx.actor.org_role == OrgRole.GUEST:
            raise PermissionDenied("guests cannot share dashboards")
        d.shared = data.shared
    if data.widgets is not None:
        _unique_ids(data.widgets)
        d.widgets = [w.model_dump(mode="json") for w in data.widgets]
    await ctx.session.flush()
    return _dash_read(d)


async def delete_dashboard(ctx: ServiceContext, dashboard_id: uuid.UUID) -> None:
    d = await _dashboard(ctx, dashboard_id, edit=True)
    await ctx.session.delete(d)
    await ctx.session.flush()


def _unique_ids(widgets: list) -> None:  # type: ignore[type-arg]
    ids = [w.id for w in widgets]
    if len(ids) != len(set(ids)):
        raise InvalidInput("widget ids must be unique")


async def status_summary(ctx: ServiceContext, project_id: uuid.UUID, *, days: int = 7) -> StatusSummary:
    """What happened in the last ``days``, what is late, what is next: data for a status update."""
    from glasshaus.scheduling import service as scheduling

    if days < 1 or days > 90:
        raise InvalidInput("days must be between 1 and 90")
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    today = _today()
    start = today - timedelta(days=days - 1)
    rows = [(t, s) for t, s in await _project_rows(ctx, project_id) if t.deleted_at is None]

    def item(t: Task, s: ProjectStatus) -> SummaryTask:
        return SummaryTask(
            key=f"{project.key}-{t.number}",
            title=t.title,
            status=s.name,
            assignee_id=t.assignee_id,
            due_date=t.due_date,
            completed_at=t.completed_at,
        )

    open_rows = [(t, s) for t, s in rows if s.category not in CLOSED]
    completed = sorted(
        (
            (t, s)
            for t, s in rows
            if s.category == StatusCategory.DONE and t.completed_at and t.completed_at.date() >= start
        ),
        key=lambda r: r[0].completed_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    overdue = sorted(
        ((t, s) for t, s in open_rows if t.due_date and t.due_date < today),
        key=lambda r: r[0].due_date or today,
    )
    soon = sorted(
        ((t, s) for t, s in open_rows if t.due_date and today <= t.due_date <= today + timedelta(days=days)),
        key=lambda r: r[0].due_date or today,
    )
    logged = await ctx.session.scalar(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.project_id == project_id, TimeEntry.spent_on >= start, TimeEntry.spent_on <= today
        )
    )
    return StatusSummary(
        project_id=project.id,
        key=project.key,
        name=project.name,
        date_from=start,
        date_to=today,
        health=await project_health(ctx, project),
        open=len(open_rows),
        done=sum(1 for _, s in rows if s.category == StatusCategory.DONE),
        overdue=len(overdue),
        completed=[item(t, s) for t, s in completed[:50]],
        in_progress=[item(t, s) for t, s in open_rows if s.category == StatusCategory.IN_PROGRESS][:50],
        overdue_tasks=[item(t, s) for t, s in overdue[:50]],
        due_soon=[item(t, s) for t, s in soon[:50]],
        warnings=[w.message for w in await scheduling.schedule_warnings(ctx, project_id)][:50],
        logged_minutes=int(logged or 0),
    )
