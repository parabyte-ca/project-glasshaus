"""Time tracking: entries, a per-user timer, timesheets and the time report.

Visibility: an entry is visible to its author, to organization admins, and to anyone who can read
its project. Logging needs TASK_UPDATE on the task; authors edit their own entries and project
admins (PROJECT_UPDATE) can edit any entry in their project.
"""

import csv
import io
import math
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import ColumnElement, Select, func, or_, select

from glasshaus.core import events
from glasshaus.core.authz import project_role, require_project, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission, project_role_permissions
from glasshaus.core.schemas import Page, decode_cursor, encode_cursor
from glasshaus.identity.models import User
from glasshaus.projects.models import Project
from glasshaus.tasks.models import Task
from glasshaus.timetracking.models import RunningTimer, TimeEntry
from glasshaus.timetracking.schemas import (
    MAX_MINUTES_PER_ENTRY,
    TimeEntryCreate,
    TimeEntryRead,
    TimeEntryUpdate,
    TimeReport,
    TimeReportRow,
    TimerRead,
    TimerStart,
    TimerStop,
    Timesheet,
    TimesheetRow,
)

MAX_RANGE_DAYS = 366


def _today() -> date:
    return datetime.now(UTC).date()


def _require_user(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise PermissionDenied("time is logged by people, not system principals")
    return ctx.actor.user_id


def _range(date_from: date | None, date_to: date | None, *, default_days: int = 7) -> tuple[date, date]:
    end = date_to or _today()
    start = date_from or end - timedelta(days=default_days - 1)
    if start > end:
        raise InvalidInput("date_from must be on or before date_to")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise InvalidInput(f"ranges are limited to {MAX_RANGE_DAYS} days")
    return start, end


def visible_entries(ctx: ServiceContext) -> ColumnElement[bool]:
    """Predicate on a query that joins ``Project`` on ``TimeEntry.project_id``."""
    if ctx.actor.is_org_admin:
        return visible_projects_clause(ctx)
    return or_(TimeEntry.user_id == ctx.actor.user_id, visible_projects_clause(ctx))


def _base() -> Select[TimeEntry, Task, Project]:
    return (
        select(TimeEntry, Task, Project)
        .join(Task, Task.id == TimeEntry.task_id)
        .join(Project, Project.id == TimeEntry.project_id)
    )


def _read(entry: TimeEntry, task: Task, project: Project) -> TimeEntryRead:
    return TimeEntryRead(
        id=entry.id,
        task_id=task.id,
        task_key=f"{project.key}-{task.number}",
        task_title=task.title,
        project_id=project.id,
        user_id=entry.user_id,
        spent_on=entry.spent_on,
        minutes=entry.minutes,
        note=entry.note,
        billable=entry.billable,
        started_at=entry.started_at,
        created_at=entry.created_at,
    )


async def _task_for_logging(ctx: ServiceContext, ref: str) -> tuple[Task, Project]:
    from glasshaus.tasks import service as tasks

    task_id = await tasks.resolve_ref(ctx, ref)
    task = await ctx.session.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise NotFound("task not found")
    try:
        project = await require_project(ctx, task.project_id, Permission.TASK_UPDATE)
    except NotFound:
        raise NotFound("task not found") from None
    return task, project


def _emit(ctx: ServiceContext, kind: str, entry: TimeEntry, task: Task, project: Project) -> None:
    events.emit(
        ctx,
        f"time.{kind}",
        "task",
        task.id,
        {
            "entry_id": str(entry.id),
            "user_id": str(entry.user_id),
            "minutes": entry.minutes,
            "spent_on": entry.spent_on.isoformat(),
            "task_key": f"{project.key}-{task.number}",
        },
        project_id=project.id,
    )


# --------------------------------------------------------------------------- entries


async def log_time(
    ctx: ServiceContext, data: TimeEntryCreate, *, started_at: datetime | None = None
) -> TimeEntryRead:
    user_id = _require_user(ctx)
    task, project = await _task_for_logging(ctx, data.task)
    spent_on = data.spent_on or _today()
    if spent_on > _today() + timedelta(days=1):
        raise InvalidInput("time cannot be logged in the future")
    entry = TimeEntry(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        task_id=task.id,
        project_id=project.id,
        user_id=user_id,
        spent_on=spent_on,
        minutes=data.minutes,
        note=data.note,
        billable=data.billable,
        started_at=started_at,
    )
    ctx.session.add(entry)
    await ctx.session.flush()
    _emit(ctx, "logged", entry, task, project)
    return _read(entry, task, project)


async def _editable(ctx: ServiceContext, entry_id: uuid.UUID) -> tuple[TimeEntry, Task, Project]:
    row = (await ctx.session.execute(_base().where(TimeEntry.id == entry_id, visible_entries(ctx)))).first()
    if row is None:
        raise NotFound("time entry not found")
    entry, task, project = row
    if entry.user_id != ctx.actor.user_id:
        role = await project_role(ctx, project)
        if role is None or Permission.PROJECT_UPDATE not in project_role_permissions(role):
            raise PermissionDenied("only the author or a project admin can change this entry")
    return entry, task, project


async def update_entry(ctx: ServiceContext, entry_id: uuid.UUID, data: TimeEntryUpdate) -> TimeEntryRead:
    entry, task, project = await _editable(ctx, entry_id)
    changes = data.model_dump(exclude_unset=True)
    for field in ("spent_on", "minutes", "note", "billable"):
        if field in changes and changes[field] is None:
            raise InvalidInput(f"{field} cannot be null")
    for field, value in changes.items():
        setattr(entry, field, value)
    await ctx.session.flush()
    _emit(ctx, "updated", entry, task, project)
    return _read(entry, task, project)


async def delete_entry(ctx: ServiceContext, entry_id: uuid.UUID) -> None:
    entry, task, project = await _editable(ctx, entry_id)
    _emit(ctx, "deleted", entry, task, project)
    await ctx.session.delete(entry)
    await ctx.session.flush()


def _filtered(
    ctx: ServiceContext,
    *,
    user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> Select[TimeEntry, Task, Project]:
    stmt = _base().where(visible_entries(ctx))
    if user_id:
        stmt = stmt.where(TimeEntry.user_id == user_id)
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)
    if task_id:
        stmt = stmt.where(TimeEntry.task_id == task_id)
    if date_from:
        stmt = stmt.where(TimeEntry.spent_on >= date_from)
    if date_to:
        stmt = stmt.where(TimeEntry.spent_on <= date_to)
    return stmt


async def list_entries(
    ctx: ServiceContext,
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    task: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> Page[TimeEntryRead]:
    from glasshaus.tasks import service as tasks

    task_id = await tasks.resolve_ref(ctx, task) if task else None
    offset = decode_cursor(cursor)
    limit = min(max(limit, 1), 500)
    stmt = (
        _filtered(
            ctx, user_id=user_id, project_id=project_id, task_id=task_id, date_from=date_from, date_to=date_to
        )
        .order_by(TimeEntry.spent_on.desc(), TimeEntry.created_at.desc(), TimeEntry.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = (await ctx.session.execute(stmt)).all()
    items = [_read(e, t, p) for e, t, p in rows[:limit]]
    return Page(items=items, next_cursor=encode_cursor(offset + limit) if len(rows) > limit else None)


async def export_csv(
    ctx: ServiceContext,
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> str:
    start, end = _range(date_from, date_to, default_days=31)
    stmt = (
        _filtered(ctx, user_id=user_id, project_id=project_id, task_id=None, date_from=start, date_to=end)
        .add_columns(User.name, User.email)
        .join(User, User.id == TimeEntry.user_id)
        .order_by(TimeEntry.spent_on, User.name, Project.key, Task.number)
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["date", "person", "email", "project", "task", "title", "minutes", "hours", "billable", "note"]
    )
    for entry, task, project, name, email in (await ctx.session.execute(stmt)).all():
        writer.writerow(
            [
                entry.spent_on.isoformat(),
                name,
                email,
                project.key,
                f"{project.key}-{task.number}",
                _safe_cell(task.title),
                entry.minutes,
                f"{entry.minutes / 60:.2f}",
                "yes" if entry.billable else "no",
                _safe_cell(entry.note),
            ]
        )
    return out.getvalue()


def _safe_cell(value: str) -> str:
    """Neutralize spreadsheet formulas (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


# --------------------------------------------------------------------------- timer


async def get_timer(ctx: ServiceContext) -> TimerRead | None:
    user_id = _require_user(ctx)
    timer = await ctx.session.get(RunningTimer, user_id)
    if timer is None:
        return None
    task = await ctx.session.get(Task, timer.task_id)
    project = await ctx.session.get(Project, task.project_id) if task else None
    if task is None or project is None:
        return None
    return TimerRead(
        task_id=task.id,
        task_key=f"{project.key}-{task.number}",
        task_title=task.title,
        started_at=timer.started_at,
        note=timer.note,
        elapsed_seconds=int((datetime.now(UTC) - timer.started_at).total_seconds()),
    )


async def start_timer(ctx: ServiceContext, data: TimerStart) -> TimerRead:
    user_id = _require_user(ctx)
    task, _ = await _task_for_logging(ctx, data.task)
    if await ctx.session.get(RunningTimer, user_id) is not None:
        raise Conflict("a timer is already running; stop it first")
    ctx.session.add(
        RunningTimer(
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            task_id=task.id,
            started_at=datetime.now(UTC),
            note=data.note,
        )
    )
    await ctx.session.flush()
    timer = await get_timer(ctx)
    assert timer is not None
    return timer


async def stop_timer(ctx: ServiceContext, data: TimerStop) -> TimeEntryRead:
    user_id = _require_user(ctx)
    timer = await ctx.session.get(RunningTimer, user_id)
    if timer is None:
        raise NotFound("no timer is running")
    elapsed = datetime.now(UTC) - timer.started_at
    minutes = min(max(math.ceil(elapsed.total_seconds() / 60), 1), MAX_MINUTES_PER_ENTRY)
    task_id, started_at, note = timer.task_id, timer.started_at, timer.note
    await ctx.session.delete(timer)
    await ctx.session.flush()
    return await log_time(
        ctx,
        TimeEntryCreate(
            task=str(task_id),
            spent_on=data.spent_on or started_at.date(),
            minutes=minutes,
            note=note if data.note is None else data.note,
            billable=data.billable,
        ),
        started_at=started_at,
    )


async def discard_timer(ctx: ServiceContext) -> None:
    user_id = _require_user(ctx)
    timer = await ctx.session.get(RunningTimer, user_id)
    if timer is not None:
        await ctx.session.delete(timer)
        await ctx.session.flush()


# --------------------------------------------------------------------------- timesheets and reports


async def _check_user(ctx: ServiceContext, user_id: uuid.UUID) -> None:
    if ctx.actor.org_role == OrgRole.GUEST and user_id != ctx.actor.user_id:
        raise PermissionDenied("guests can only see their own timesheet")
    if await ctx.session.get(User, user_id) is None:
        raise NotFound("user not found")


async def timesheet(
    ctx: ServiceContext, user_id: uuid.UUID | None, date_from: date | None, date_to: date | None
) -> Timesheet:
    """One person's time per task and day. Others' entries appear only where you can read the project."""
    uid = user_id or _require_user(ctx)
    await _check_user(ctx, uid)
    start, end = _range(date_from, date_to)
    rows = (
        await ctx.session.execute(
            _filtered(ctx, user_id=uid, project_id=None, task_id=None, date_from=start, date_to=end).order_by(
                Project.key, Task.number
            )
        )
    ).all()
    by_task: dict[uuid.UUID, TimesheetRow] = {}
    totals: dict[date, int] = defaultdict(int)
    billable = 0
    for entry, task, project in rows:
        row = by_task.get(task.id)
        if row is None:
            row = by_task[task.id] = TimesheetRow(
                project_id=project.id,
                project_key=project.key,
                project_name=project.name,
                task_id=task.id,
                task_key=f"{project.key}-{task.number}",
                task_title=task.title,
                minutes_by_day={},
                total=0,
            )
        row.minutes_by_day[entry.spent_on] = row.minutes_by_day.get(entry.spent_on, 0) + entry.minutes
        row.total += entry.minutes
        totals[entry.spent_on] += entry.minutes
        billable += entry.minutes if entry.billable else 0
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return Timesheet(
        user_id=uid,
        date_from=start,
        date_to=end,
        days=days,
        rows=list(by_task.values()),
        totals_by_day=dict(totals),
        total=sum(totals.values()),
        billable_total=billable,
    )


async def time_report(
    ctx: ServiceContext,
    *,
    date_from: date | None,
    date_to: date | None,
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> TimeReport:
    """Minutes per person and project: who put time towards which projects."""
    if ctx.actor.org_role == OrgRole.GUEST:
        user_id = ctx.actor.user_id
    start, end = _range(date_from, date_to, default_days=30)
    stmt = (
        select(
            TimeEntry.user_id,
            User.name,
            Project.id,
            Project.key,
            Project.name,
            func.sum(TimeEntry.minutes),
            func.sum(TimeEntry.minutes).filter(TimeEntry.billable.is_(True)),
        )
        .join(Project, Project.id == TimeEntry.project_id)
        .join(User, User.id == TimeEntry.user_id)
        .where(visible_entries(ctx), TimeEntry.spent_on >= start, TimeEntry.spent_on <= end)
        .group_by(TimeEntry.user_id, User.name, Project.id, Project.key, Project.name)
        .order_by(User.name, Project.key)
    )
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)
    if user_id:
        stmt = stmt.where(TimeEntry.user_id == user_id)
    rows = [
        TimeReportRow(
            user_id=uid,
            user_name=name,
            project_id=pid,
            project_key=key,
            project_name=pname,
            minutes=int(minutes or 0),
            billable_minutes=int(bill or 0),
        )
        for uid, name, pid, key, pname, minutes, bill in (await ctx.session.execute(stmt)).all()
    ]
    return TimeReport(date_from=start, date_to=end, rows=rows, total=sum(r.minutes for r in rows))


async def logged_by_task(ctx: ServiceContext, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Total logged minutes per task (all authors; callers check task visibility)."""
    if not task_ids:
        return {}
    rows = await ctx.session.execute(
        select(TimeEntry.task_id, func.sum(TimeEntry.minutes))
        .where(TimeEntry.task_id.in_(task_ids))
        .group_by(TimeEntry.task_id)
    )
    return {tid: int(total or 0) for tid, total in rows.all()}
