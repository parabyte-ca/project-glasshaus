"""Reporting lines and the My team page.

A manager sees the people below them: direct reports by default, everyone further down on request.
With the organization's default visibility ("all") that includes their reports' work in every
project, even ones the manager is not a member of; "shared" limits it to projects the manager can
open (elsewhere only counts). Opening a person's task list is audited.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.audit import service as audit
from glasshaus.core.authz import visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound
from glasshaus.identity.models import ASSISTANT_KIND, User
from glasshaus.insights import calc
from glasshaus.logs import get_logger
from glasshaus.people.schemas import TeamMember, TeamProject, TeamRead, TeamTask, TeamTasks, Visibility
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Task
from glasshaus.timetracking.models import TimeEntry

log = get_logger(__name__)

MAX_DEPTH = 20  # reporting chains longer than this are cut (and loops are refused)
MAX_PEOPLE = 500
STALE_DAYS = 5
OPEN = (StatusCategory.BACKLOG, StatusCategory.TODO, StatusCategory.IN_PROGRESS)


# --------------------------------------------------------------------------- reporting lines


async def would_loop(session: AsyncSession, user_id: uuid.UUID, manager_id: uuid.UUID) -> bool:
    """Whether making ``manager_id`` this person's manager creates a loop (or reports to themselves)."""
    current: uuid.UUID | None = manager_id
    for _ in range(MAX_DEPTH + 1):
        if current is None:
            return False
        if current == user_id:
            return True
        current = await session.scalar(select(User.manager_id).where(User.id == current))
    return True  # too deep: treat as a loop rather than walk forever


async def set_manager(session: AsyncSession, user: User, manager_id: uuid.UUID | None, source: str) -> bool:
    """Record who ``user`` reports to. Returns False (and changes nothing) for a loop or unknown person."""
    if manager_id is not None:
        manager = await session.get(User, manager_id)
        if manager is None or manager.kind == ASSISTANT_KIND or manager.tenant_id != user.tenant_id:
            return False
        if await would_loop(session, user.id, manager_id):
            log.warning("people.manager_loop", user=str(user.id), manager=str(manager_id))
            return False
    user.manager_id, user.manager_source = manager_id, source
    return True


async def team_ids(session: AsyncSession, manager_id: uuid.UUID, *, everyone: bool) -> dict[uuid.UUID, int]:
    """Active people below a manager, with their level (1 = direct report)."""
    base = select(User.id, literal(1).label("level")).where(
        User.manager_id == manager_id, User.is_active.is_(True), User.kind != ASSISTANT_KIND
    )
    if not everyone:
        rows = (await session.execute(base.limit(MAX_PEOPLE))).all()
        return {r.id: 1 for r in rows}
    tree = base.cte("tree", recursive=True)
    deeper = select(User.id, (tree.c.level + 1).label("level")).where(
        User.manager_id == tree.c.id,
        User.is_active.is_(True),
        User.kind != ASSISTANT_KIND,
        tree.c.level < MAX_DEPTH,
    )
    tree = tree.union(deeper)  # UNION (not ALL) also stops a loop that slipped in
    rows = (await session.execute(select(tree.c.id, func.min(tree.c.level)).group_by(tree.c.id))).all()
    return dict(list(rows)[:MAX_PEOPLE])


async def direct_report_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count()).where(
                User.manager_id == user_id, User.is_active.is_(True), User.kind != ASSISTANT_KIND
            )
        )
        or 0
    )


# --------------------------------------------------------------------------- My team


async def visibility(ctx: ServiceContext) -> Visibility:
    from glasshaus.governance.models import OrgSettings

    org = await ctx.session.get(OrgSettings, ctx.tenant_id)
    return "shared" if org is not None and org.manager_visibility == "shared" else "all"


def _me(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise InvalidInput("My team belongs to a person")
    return ctx.actor.user_id


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _visible_ids(ctx: ServiceContext, project_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not project_ids:
        return set()
    rows = await ctx.session.scalars(
        select(Project.id).where(Project.id.in_(project_ids), visible_projects_clause(ctx))
    )
    return set(rows.all())


async def my_team(ctx: ServiceContext, *, everyone: bool = False) -> TeamRead:
    me = _me(ctx)
    mode = await visibility(ctx)
    levels = await team_ids(ctx.session, me, everyone=everyone)
    direct = await direct_report_count(ctx.session, me)
    if not levels:
        return TeamRead(visibility=mode, direct_reports=direct, people=[])
    ids = list(levels)
    now = datetime.now(UTC)
    today = now.date()
    week_end = today + timedelta(days=6 - today.weekday())
    this_monday = _monday(today)
    last_monday = this_monday - timedelta(days=7)
    week_ago = now - timedelta(days=7)
    stale_before = now - timedelta(days=STALE_DAYS)

    people = (await ctx.session.scalars(select(User).where(User.id.in_(ids)))).all()

    # Open work per person and project, in one pass.
    is_open = ProjectStatus.category.in_(OPEN)
    per_project = (
        await ctx.session.execute(
            select(
                Task.assignee_id,
                Task.project_id,
                func.count().filter(is_open).label("open"),
                func.count()
                .filter(ProjectStatus.category == StatusCategory.IN_PROGRESS)
                .label("in_progress"),
                func.count().filter(is_open, Task.due_date < today).label("overdue"),
                func.count()
                .filter(is_open, Task.due_date >= today, Task.due_date <= week_end)
                .label("due_week"),
                func.count()
                .filter(ProjectStatus.category == StatusCategory.IN_PROGRESS, Task.updated_at < stale_before)
                .label("stale"),
                func.count()
                .filter(ProjectStatus.category == StatusCategory.DONE, Task.completed_at >= week_ago)
                .label("done_week"),
            )
            .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            .join(Project, Project.id == Task.project_id)
            .where(
                Task.assignee_id.in_(ids),
                Task.deleted_at.is_(None),
                Project.archived_at.is_(None),
                is_open | (Task.completed_at >= week_ago),
            )
            .group_by(Task.assignee_id, Task.project_id)
        )
    ).all()
    project_ids = {r.project_id for r in per_project}
    visible = await _visible_ids(ctx, project_ids)

    # Project health (overdue share of open work), for the projects involved.
    health_rows = (
        await ctx.session.execute(
            select(
                Task.project_id,
                func.count().filter(ProjectStatus.category != StatusCategory.CANCELLED).label("total"),
                func.count().filter(ProjectStatus.category == StatusCategory.DONE).label("done"),
                func.count().filter(is_open, Task.due_date < today).label("overdue"),
            )
            .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            .where(Task.project_id.in_(project_ids), Task.deleted_at.is_(None))
            .group_by(Task.project_id)
        )
    ).all()
    health = {r.project_id: calc.health(r.total, r.done, r.overdue, 0) for r in health_rows}
    projects = {
        p.id: p for p in (await ctx.session.scalars(select(Project).where(Project.id.in_(project_ids)))).all()
    }

    # Time logged this week and last week.
    logged: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0])
    for row in (
        await ctx.session.execute(
            select(
                TimeEntry.user_id,
                func.coalesce(func.sum(TimeEntry.minutes).filter(TimeEntry.spent_on >= this_monday), 0),
                func.coalesce(func.sum(TimeEntry.minutes).filter(TimeEntry.spent_on < this_monday), 0),
            )
            .where(TimeEntry.user_id.in_(ids), TimeEntry.spent_on >= last_monday)
            .group_by(TimeEntry.user_id)
        )
    ).all():
        logged[row[0]] = [int(row[1]), int(row[2])]

    recent = await _recent_done(ctx, ids, week_ago, visible if mode == "shared" else None)

    totals: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_person: dict[uuid.UUID, list[TeamProject]] = defaultdict(list)
    for r in per_project:
        t = totals[r.assignee_id]
        for k in ("open", "in_progress", "overdue", "due_week", "stale", "done_week"):
            t[k] += getattr(r, k)
        if r.open:
            p = projects[r.project_id]
            shown = mode == "all" or r.project_id in visible
            by_person[r.assignee_id].append(
                TeamProject(
                    id=p.id,
                    key=p.key if shown else None,
                    name=p.name if shown else None,
                    health=health.get(p.id, "on_track"),
                    open_tasks=r.open,
                    visible=r.project_id in visible,
                )
            )

    members = [
        TeamMember(
            id=u.id,
            name=u.name,
            email=u.email,
            job_title=u.job_title,
            department=u.department,
            manager_id=u.manager_id,
            level=levels[u.id],
            open=totals[u.id]["open"],
            in_progress=totals[u.id]["in_progress"],
            overdue=totals[u.id]["overdue"],
            due_this_week=totals[u.id]["due_week"],
            logged_this_week=logged[u.id][0],
            logged_last_week=logged[u.id][1],
            capacity_week=u.capacity_minutes * len(u.working_days),
            completed_last_7_days=totals[u.id]["done_week"],
            stale=totals[u.id]["stale"],
            recent=recent.get(u.id, [])[:3],
            projects=sorted(by_person[u.id], key=lambda p: -p.open_tasks),
        )
        for u in people
    ]
    members.sort(key=lambda m: (m.level, m.name.lower()))
    return TeamRead(visibility=mode, direct_reports=direct, people=members)


def _task_query() -> Any:
    return (
        select(Task, ProjectStatus, Project)
        .join(ProjectStatus, ProjectStatus.id == Task.status_id)
        .join(Project, Project.id == Task.project_id)
        .where(Task.deleted_at.is_(None), Project.archived_at.is_(None))
    )


def _team_task(t: Task, s: ProjectStatus, p: Project) -> TeamTask:
    return TeamTask(
        id=t.id,
        key=f"{p.key}-{t.number}",
        title=t.title,
        project_key=p.key,
        project_name=p.name,
        status=s.name,
        category=s.category.value,
        priority=t.priority.value,
        due_date=t.due_date,
        updated_at=t.updated_at,
        completed_at=t.completed_at,
    )


async def _recent_done(
    ctx: ServiceContext, ids: list[uuid.UUID], since: datetime, only: set[uuid.UUID] | None
) -> dict[uuid.UUID, list[TeamTask]]:
    stmt = _task_query().where(
        Task.assignee_id.in_(ids),
        ProjectStatus.category == StatusCategory.DONE,
        Task.completed_at >= since,
    )
    if only is not None:
        stmt = stmt.where(Task.project_id.in_(only or {uuid.UUID(int=0)}))
    out: dict[uuid.UUID, list[TeamTask]] = defaultdict(list)
    for t, s, p in (await ctx.session.execute(stmt.order_by(Task.completed_at.desc()).limit(500))).all():
        if t.assignee_id and len(out[t.assignee_id]) < 3:
            out[t.assignee_id].append(_team_task(t, s, p))
    return out


async def report_tasks(ctx: ServiceContext, person_id: uuid.UUID, *, done: bool = False) -> TeamTasks:
    """One report's open tasks (or those finished in the last 30 days), for their manager."""
    me = _me(ctx)
    levels = await team_ids(ctx.session, me, everyone=True)
    if person_id not in levels:
        raise NotFound("this person does not report to you")
    mode = await visibility(ctx)
    stmt = _task_query().where(Task.assignee_id == person_id)
    if done:
        stmt = stmt.where(
            ProjectStatus.category == StatusCategory.DONE,
            Task.completed_at >= datetime.now(UTC) - timedelta(days=30),
        ).order_by(Task.completed_at.desc())
    else:
        stmt = stmt.where(ProjectStatus.category.in_(OPEN)).order_by(
            case((Task.due_date.is_(None), 1), else_=0), Task.due_date, Task.number
        )
    rows = (await ctx.session.execute(stmt.limit(300))).all()
    hidden = 0
    if mode == "shared":
        visible = await _visible_ids(ctx, {p.id for _, _, p in rows})
        kept = [r for r in rows if r[2].id in visible]
        hidden, rows = len(rows) - len(kept), kept
    await audit.record(
        ctx.actor,
        "team.tasks_viewed",
        outcome="ok",
        target=str(person_id),
        detail={"done": done, "visibility": mode, "shown": len(rows)},
    )
    return TeamTasks(person=person_id, hidden=hidden, tasks=[_team_task(t, s, p) for t, s, p in rows])
