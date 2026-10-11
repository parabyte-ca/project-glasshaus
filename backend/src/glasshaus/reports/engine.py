"""Turns a report definition into one grouped query (plus one for totals).

Every query is limited to what the person running it can see: tasks in projects they can read, and
time entries they may see (their own, or in projects they can read). A shared report therefore
shows each viewer their own numbers, never the author's.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.sql.elements import ColumnElement

from glasshaus.core.authz import require_project, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound
from glasshaus.core.rbac import Permission
from glasshaus.fields.models import CustomField, FieldType
from glasshaus.identity.models import User
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.reports.schemas import (
    CUSTOM_FIELD_PREFIX,
    Column,
    DateFilter,
    ReportDefinition,
    ReportResult,
    Row,
)
from glasshaus.tasks.models import Task
from glasshaus.timetracking.models import TimeEntry
from glasshaus.timetracking.service import visible_entries

MAX_GROUPS = 5000
MAX_CUSTOM_DAYS = 1100
CLOSED = (StatusCategory.DONE, StatusCategory.CANCELLED)

DIMENSION_LABELS = {
    "project": "Project",
    "status": "Status",
    "status_category": "Status category",
    "priority": "Priority",
    "assignee": "Assignee",
    "reporter": "Reporter",
    "tag": "Tag",
    "due_week": "Due (week)",
    "due_month": "Due (month)",
    "created_week": "Created (week)",
    "created_month": "Created (month)",
    "completed_week": "Completed (week)",
    "completed_month": "Completed (month)",
    "person": "Person",
    "task": "Task",
    "day": "Day",
    "week": "Week",
    "month": "Month",
    "billable": "Billable",
}
MEASURE_INFO: dict[str, tuple[str, str]] = {
    "count": ("Tasks", "count"),
    "open": ("Open", "count"),
    "done": ("Done", "count"),
    "overdue": ("Overdue", "count"),
    "estimate_hours": ("Estimate (h)", "hours"),
    "avg_age_days": ("Average age of open tasks (days)", "days"),
    "avg_cycle_days": ("Average time to complete (days)", "days"),
    "on_time_pct": ("Completed on time (%)", "percent"),
    "hours": ("Hours", "hours"),
    "billable_hours": ("Billable hours", "hours"),
    "entries": ("Time entries", "count"),
    "people": ("People", "count"),
}
CATEGORY_LABELS = {
    "backlog": "Backlog",
    "todo": "To do",
    "in_progress": "In progress",
    "done": "Done",
    "cancelled": "Cancelled",
}
DATE_DIMENSIONS = {
    "due_week",
    "due_month",
    "created_week",
    "created_month",
    "completed_week",
    "completed_month",
    "day",
    "week",
    "month",
}


def today() -> date:
    return datetime.now(UTC).date()


def date_range(f: DateFilter, now: date) -> tuple[date, date]:
    """The days a preset covers, inclusive."""
    if f.preset == "custom":
        assert f.date_from is not None
        assert f.date_to is not None
        if (f.date_to - f.date_from).days > MAX_CUSTOM_DAYS:
            raise InvalidInput(f"custom ranges are limited to {MAX_CUSTOM_DAYS} days")
        return f.date_from, f.date_to
    if f.preset in ("last_7_days", "last_30_days", "last_90_days"):
        days = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}[f.preset]
        return now - timedelta(days=days - 1), now
    if f.preset == "next_30_days":
        return now, now + timedelta(days=29)
    if f.preset == "this_month":
        return now.replace(day=1), now
    if f.preset == "last_month":
        end = now.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if f.preset == "this_quarter":
        return date(now.year, 3 * ((now.month - 1) // 3) + 1, 1), now
    return date(now.year, 1, 1), now  # this_year


@dataclass
class _Dim:
    name: str
    expr: ColumnElement[Any]
    empty: str  # label for a missing value


def _utc_day(column: Any) -> ColumnElement[Any]:
    return func.timezone("UTC", column)


def _trunc(unit: str, column: Any) -> ColumnElement[Any]:
    return cast(func.date_trunc(unit, column), Date)


def _task_dimension(name: str) -> _Dim:
    if name.startswith(CUSTOM_FIELD_PREFIX):
        field_id = name.removeprefix(CUSTOM_FIELD_PREFIX)
        return _Dim(name, Task.custom_fields[field_id].astext, "(none)")
    table: dict[str, tuple[Any, str]] = {
        "project": (Task.project_id, ""),
        "status": (ProjectStatus.name, ""),
        "status_category": (ProjectStatus.category, ""),
        "priority": (Task.priority, ""),
        "assignee": (Task.assignee_id, "Unassigned"),
        "reporter": (Task.reporter_id, "Unknown"),
        "tag": (func.unnest(Task.tags), ""),
        "due_week": (_trunc("week", Task.due_date), "No due date"),
        "due_month": (_trunc("month", Task.due_date), "No due date"),
        "created_week": (_trunc("week", _utc_day(Task.created_at)), ""),
        "created_month": (_trunc("month", _utc_day(Task.created_at)), ""),
        "completed_week": (_trunc("week", _utc_day(Task.completed_at)), "Not completed"),
        "completed_month": (_trunc("month", _utc_day(Task.completed_at)), "Not completed"),
    }
    expr, empty = table[name]
    return _Dim(name, expr, empty)


def _time_dimension(name: str) -> _Dim:
    table: dict[str, tuple[Any, str]] = {
        "project": (TimeEntry.project_id, ""),
        "person": (TimeEntry.user_id, ""),
        "task": (TimeEntry.task_id, ""),
        "day": (TimeEntry.spent_on, ""),
        "week": (_trunc("week", TimeEntry.spent_on), ""),
        "month": (_trunc("month", TimeEntry.spent_on), ""),
        "billable": (TimeEntry.billable, ""),
    }
    expr, empty = table[name]
    return _Dim(name, expr, empty)


def _task_measures(now: datetime) -> dict[str, Callable[[], ColumnElement[Any]]]:
    is_open = ProjectStatus.category.not_in(CLOSED)
    is_done = ProjectStatus.category == StatusCategory.DONE
    done_with_due = (is_done, Task.due_date.is_not(None), Task.completed_at.is_not(None))
    days = 86400.0
    return {
        "count": lambda: func.count(Task.id),
        "open": lambda: func.count(Task.id).filter(is_open),
        "done": lambda: func.count(Task.id).filter(is_done),
        "overdue": lambda: func.count(Task.id).filter(is_open, Task.due_date < now.date()),
        "estimate_hours": lambda: func.coalesce(func.sum(Task.estimate_minutes), 0) / 60.0,
        "avg_age_days": lambda: func.avg(func.extract("epoch", now - Task.created_at) / days).filter(is_open),
        "avg_cycle_days": lambda: func.avg(
            func.extract("epoch", Task.completed_at - Task.created_at) / days
        ).filter(is_done, Task.completed_at.is_not(None)),
        "on_time_pct": lambda: (
            100.0
            * func.count(Task.id).filter(
                *done_with_due, cast(_utc_day(Task.completed_at), Date) <= Task.due_date
            )
            / func.nullif(func.count(Task.id).filter(*done_with_due), 0)
        ),
    }


def _time_measures() -> dict[str, Callable[[], ColumnElement[Any]]]:
    return {
        "hours": lambda: func.coalesce(func.sum(TimeEntry.minutes), 0) / 60.0,
        "billable_hours": lambda: (
            func.coalesce(func.sum(TimeEntry.minutes).filter(TimeEntry.billable), 0) / 60.0
        ),
        "entries": lambda: func.count(TimeEntry.id),
        "people": lambda: func.count(func.distinct(TimeEntry.user_id)),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


async def _custom_field_options(ctx: ServiceContext, name: str) -> dict[str, str]:
    field = await ctx.session.get(CustomField, uuid.UUID(name.removeprefix(CUSTOM_FIELD_PREFIX)))
    if field is None:
        raise NotFound("custom field not found")
    await require_project(ctx, field.project_id, Permission.PROJECT_READ)  # NotFound when not visible
    if field.type != FieldType.SELECT:
        raise InvalidInput("only single-select custom fields can be used for grouping")
    return {str(o["id"]): str(o["label"]) for o in field.options}


async def _labels(ctx: ServiceContext, dim: str, keys: set[Any]) -> dict[Any, str]:
    """Human labels for grouping values (names for ids, readable dates and categories)."""
    present = {k for k in keys if k is not None}
    if dim == "project" and present:
        projects = await ctx.session.execute(
            select(Project.id, Project.key, Project.name).where(Project.id.in_(present))
        )
        return {pid: f"{key} {name}" for pid, key, name in projects}
    if dim in ("assignee", "reporter", "person") and present:
        people = await ctx.session.execute(select(User.id, User.name).where(User.id.in_(present)))
        return {uid: str(name) for uid, name in people}
    if dim == "task" and present:
        task_rows = await ctx.session.execute(
            select(Task.id, Project.key, Task.number, Task.title)
            .join(Project, Project.id == Task.project_id)
            .where(Task.id.in_(present))
        )
        return {tid: f"{key}-{number} {title}" for tid, key, number, title in task_rows}
    if dim == "status_category":
        return {k: CATEGORY_LABELS.get(str(getattr(k, "value", k)), str(k)) for k in present}
    if dim == "priority":
        return {k: str(getattr(k, "value", k)).capitalize() for k in present}
    if dim == "billable":
        return {True: "Billable", False: "Not billable"}
    if dim.endswith("month"):
        return {k: k.strftime("%b %Y") for k in present}
    if dim.endswith("week") or dim == "week":
        return {k: f"Week of {k.isoformat()}" for k in present}
    if dim == "day":
        return {k: k.isoformat() for k in present}
    return {k: str(k) for k in present}


def _key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(getattr(value, "value", value))


async def run(ctx: ServiceContext, definition: ReportDefinition) -> ReportResult:
    now = datetime.now(UTC)
    tasks = definition.source == "tasks"
    f = definition.filters

    custom_labels: dict[str, dict[str, str]] = {}
    for dim in definition.group_by:
        if dim.startswith(CUSTOM_FIELD_PREFIX):
            custom_labels[dim] = await _custom_field_options(ctx, dim)

    dims = [(_task_dimension if tasks else _time_dimension)(d) for d in definition.group_by]
    measure_table = _task_measures(now) if tasks else _time_measures()
    measures = [measure_table[m]() for m in definition.measures]

    where: list[ColumnElement[bool]] = []
    if tasks:
        where += [visible_projects_clause(ctx), Task.deleted_at.is_(None)]
        if f.status_categories:
            where.append(ProjectStatus.category.in_(f.status_categories))
        if f.priorities:
            where.append(Task.priority.in_(f.priorities))
        if f.people:
            where.append(Task.assignee_id.in_(f.people))
        if f.tags:
            where.append(Task.tags.overlap(f.tags))
    else:
        where += [visible_entries(ctx), Task.deleted_at.is_(None)]
        if f.people:
            where.append(TimeEntry.user_id.in_(f.people))
        if f.billable is not None:
            where.append(TimeEntry.billable.is_(f.billable))
    if f.project_ids:
        where.append(Project.id.in_(f.project_ids))

    start = end = None
    if f.date is not None:
        start, end = date_range(f.date, now.date())
        if f.date.field in ("due", "spent"):
            column = Task.due_date if f.date.field == "due" else TimeEntry.spent_on
            where += [column >= start, column <= end]
        else:
            column = Task.created_at if f.date.field == "created" else Task.completed_at
            where += [
                column >= datetime.combine(start, time.min, UTC),
                column < datetime.combine(end + timedelta(days=1), time.min, UTC),
            ]

    def base(*columns: Any) -> Any:
        if tasks:
            stmt = (
                select(*columns)
                .select_from(Task)
                .join(Project, Project.id == Task.project_id)
                .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            )
        else:
            stmt = (
                select(*columns)
                .select_from(TimeEntry)
                .join(Task, Task.id == TimeEntry.task_id)
                .join(Project, Project.id == TimeEntry.project_id)
            )
        return stmt.where(*where)

    totals_row = (await ctx.session.execute(base(*measures))).one()
    totals = [_number(v) for v in totals_row]

    grouped: list[Any] = []
    if dims:
        labelled = [d.expr.label(f"dim{i}") for i, d in enumerate(dims)]
        stmt = base(*labelled, *measures).group_by(*(literal_column(f"dim{i}") for i in range(len(dims))))
        grouped = list((await ctx.session.execute(stmt.limit(MAX_GROUPS + 1))).all())

    label_maps: list[dict[Any, str]] = []
    for i, d in enumerate(dims):
        keys = {row[i] for row in grouped}
        if d.name in custom_labels:
            options = custom_labels[d.name]
            label_maps.append({k: options.get(str(k), "(removed option)") for k in keys if k is not None})
        else:
            label_maps.append(await _labels(ctx, d.name, keys))

    rows: list[Row] = []
    for row in grouped[:MAX_GROUPS]:
        raw = row[: len(dims)]
        labels = [
            label_maps[i].get(value, str(value)) if value is not None else (dims[i].empty or "(none)")
            for i, value in enumerate(raw)
        ]
        rows.append(
            Row(keys=[_key(v) for v in raw], labels=labels, values=[_number(v) for v in row[len(dims) :]])
        )

    sort = definition.sort
    if sort.by == "label":
        # Dates sort by date, everything else by its label.
        def by_label(r: Row) -> tuple[str, ...]:
            return tuple(
                (r.keys[i] or "") if d.name in DATE_DIMENSIONS else r.labels[i].lower()
                for i, d in enumerate(dims)
            )

        rows.sort(key=by_label, reverse=sort.descending)
    else:
        index = definition.measures.index(sort.by)  # type: ignore[arg-type]
        present = [r for r in rows if r.values[index] is not None]
        missing = [r for r in rows if r.values[index] is None]
        present.sort(key=lambda r: r.values[index] or 0.0, reverse=sort.descending)
        rows = present + missing

    columns = [
        Column(
            key=d.name,
            label=DIMENSION_LABELS.get(d.name, "Custom field"),
            kind="dimension",
            unit="date" if d.name in DATE_DIMENSIONS else "text",
        )
        for d in dims
    ]
    for d_index, d in enumerate(dims):
        if d.name.startswith(CUSTOM_FIELD_PREFIX):
            field = await ctx.session.get(CustomField, uuid.UUID(d.name.removeprefix(CUSTOM_FIELD_PREFIX)))
            columns[d_index].label = field.name if field else "Custom field"
    columns += [
        Column(key=m, label=MEASURE_INFO[m][0], kind="measure", unit=MEASURE_INFO[m][1])
        for m in definition.measures
    ]
    return ReportResult(
        columns=columns,
        rows=rows[: definition.limit],
        totals=totals,
        total_groups=len(grouped),
        truncated=len(grouped) > definition.limit,
        date_from=start,
        date_to=end,
        generated_at=now,
    )
