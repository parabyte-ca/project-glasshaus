"""Task services."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, case, func, nulls_last, or_, select, update
from sqlalchemy.orm.exc import StaleDataError

from glasshaus.core import events
from glasshaus.core.authz import project_role, require_project, require_scope, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied, PreconditionFailed, ServiceError
from glasshaus.core.rbac import Permission, project_role_permissions
from glasshaus.core.schemas import Page, decode_cursor, encode_cursor
from glasshaus.identity.models import User
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.projects.schemas import DeletePreview, StatusRead
from glasshaus.tasks.models import PRIORITY_RANK, Task
from glasshaus.tasks.schemas import (
    BulkResult,
    TaskBulkUpdate,
    TaskCreate,
    TaskQuery,
    TaskRead,
    TaskSort,
    TaskUpdate,
)

REF_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,9})-(\d+)$")
POSITION_STEP = 1024.0
CLOSED = (StatusCategory.DONE, StatusCategory.CANCELLED)


# --------------------------------------------------------------------------- helpers


async def _to_read(ctx: ServiceContext, tasks: list[Task]) -> list[TaskRead]:
    if not tasks:
        return []
    project_ids = {t.project_id for t in tasks}
    keys = dict(
        (await ctx.session.execute(select(Project.id, Project.key).where(Project.id.in_(project_ids)))).all()
    )
    statuses = {
        s.id: StatusRead.model_validate(s)
        for s in (
            await ctx.session.scalars(select(ProjectStatus).where(ProjectStatus.project_id.in_(project_ids)))
        )
    }
    return [
        TaskRead.model_validate(
            {
                **{c: getattr(t, c) for c in TaskRead.model_fields if c not in ("key", "status")},
                "key": f"{keys[t.project_id]}-{t.number}",
                "status": statuses[t.status_id],
            }
        )
        for t in tasks
    ]


async def _load(
    ctx: ServiceContext, task_id: uuid.UUID, permission: Permission, *, deleted: bool = False
) -> Task:
    task = await ctx.session.get(Task, task_id)
    if task is None or (task.deleted_at is not None and not deleted):
        raise NotFound("task not found")
    try:
        await require_project(ctx, task.project_id, permission)
    except NotFound:
        raise NotFound("task not found") from None
    return task


async def _status(ctx: ServiceContext, project_id: uuid.UUID, status_id: uuid.UUID | None) -> ProjectStatus:
    if status_id is not None:
        status = await ctx.session.get(ProjectStatus, status_id)
        if status is None or status.project_id != project_id:
            raise InvalidInput("status does not belong to this project")
        return status
    statuses = list(
        (
            await ctx.session.scalars(
                select(ProjectStatus)
                .where(ProjectStatus.project_id == project_id)
                .order_by(ProjectStatus.position)
            )
        ).all()
    )
    for category in (StatusCategory.TODO, StatusCategory.BACKLOG):
        for s in statuses:
            if s.category == category:
                return s
    if not statuses:
        raise InvalidInput("project has no statuses")
    return statuses[0]


async def _status_in_category(
    ctx: ServiceContext, project_id: uuid.UUID, category: StatusCategory
) -> ProjectStatus:
    status = await ctx.session.scalar(
        select(ProjectStatus)
        .where(ProjectStatus.project_id == project_id, ProjectStatus.category == category)
        .order_by(ProjectStatus.position)
        .limit(1)
    )
    if status is None:
        raise InvalidInput(f"project has no '{category.value}' status")
    return status


async def _check_assignee(ctx: ServiceContext, project: Project, user_id: uuid.UUID) -> None:
    user = await ctx.session.get(User, user_id)
    if user is None or not user.is_active:
        raise InvalidInput("assignee not found")
    from glasshaus.core.context import Actor
    from glasshaus.core.context import ServiceContext as Ctx

    probe = Ctx(
        session=ctx.session,
        actor=Actor(tenant_id=ctx.tenant_id, user_id=user.id, org_role=user.org_role, method="system"),
    )
    if await project_role(probe, project) is None:
        raise InvalidInput("assignee has no access to this project")


async def _check_parent(
    ctx: ServiceContext, task: Task | None, project_id: uuid.UUID, parent_id: uuid.UUID
) -> None:
    parent = await ctx.session.get(Task, parent_id)
    if parent is None or parent.deleted_at is not None or parent.project_id != project_id:
        raise InvalidInput("parent must be a task in the same project")
    if task is not None:
        cursor: Task | None = parent
        depth = 0
        while cursor is not None:
            if cursor.id == task.id:
                raise InvalidInput("a task cannot be its own ancestor")
            depth += 1
            if depth > 50:
                raise InvalidInput("subtask nesting is too deep")
            cursor = await ctx.session.get(Task, cursor.parent_id) if cursor.parent_id else None


def _apply_status(task: Task, status: ProjectStatus) -> None:
    task.status_id = status.id
    if status.category in CLOSED:
        task.completed_at = task.completed_at or datetime.now(UTC)
    else:
        task.completed_at = None


# --------------------------------------------------------------------------- queries


def _sort_clause(query: TaskQuery) -> list[Any]:
    priority_rank = case({p.value: r for p, r in PRIORITY_RANK.items()}, value=Task.priority)
    column: Any = {
        TaskSort.POSITION: Task.position,
        TaskSort.CREATED: Task.created_at,
        TaskSort.UPDATED: Task.updated_at,
        TaskSort.DUE: Task.due_date,
        TaskSort.PRIORITY: priority_rank,
        TaskSort.NUMBER: Task.number,
        TaskSort.TITLE: func.lower(Task.title),
    }[query.sort]
    if query.sort_field:
        column = Task.custom_fields[str(query.sort_field)].astext
    primary = column.desc() if query.descending else column.asc()
    return [nulls_last(primary), Task.id]


def _custom_field_condition(spec: str) -> Any:
    key, sep, raw = spec.partition("=")
    try:
        field_id = str(uuid.UUID(key))
    except ValueError:
        raise InvalidInput(f"invalid custom field filter {spec!r}; expected <field_id>=<value>") from None
    if not sep:
        return Task.custom_fields.has_key(field_id)
    candidates: list[Any] = [raw, [raw]]
    if raw in ("true", "false"):
        candidates.append(raw == "true")
    try:
        number = float(raw)
        candidates.append(int(number) if number.is_integer() else number)
    except ValueError:
        pass
    return or_(*(Task.custom_fields.contains({field_id: c}) for c in candidates))


def _filtered(ctx: ServiceContext, query: TaskQuery) -> Select[Task]:
    stmt = select(Task).join(Project, Project.id == Task.project_id).where(visible_projects_clause(ctx))
    conds: list[Any] = []
    if not query.include_deleted:
        conds.append(Task.deleted_at.is_(None))
    if query.project_id:
        conds.append(Task.project_id == query.project_id)
    if query.workspace_id:
        conds.append(Project.workspace_id == query.workspace_id)
    if query.status_ids:
        conds.append(Task.status_id.in_(query.status_ids))
    if query.status_categories:
        conds.append(
            Task.status_id.in_(
                select(ProjectStatus.id).where(ProjectStatus.category.in_(query.status_categories))
            )
        )
    assignee_conds = []
    if query.assignee_ids:
        assignee_conds.append(Task.assignee_id.in_(query.assignee_ids))
    if query.unassigned:
        assignee_conds.append(Task.assignee_id.is_(None))
    if assignee_conds:
        conds.append(or_(*assignee_conds))
    if query.priorities:
        conds.append(Task.priority.in_(query.priorities))
    if query.parent_id:
        conds.append(Task.parent_id == query.parent_id)
    elif query.top_level_only:
        conds.append(Task.parent_id.is_(None))
    if query.tags:
        conds.append(Task.tags.contains(query.tags))
    if query.due_before:
        conds.append(Task.due_date <= query.due_before)
    if query.due_after:
        conds.append(Task.due_date >= query.due_after)
    for spec in query.cf or []:
        conds.append(_custom_field_condition(spec))
    if query.scheduled_from or query.scheduled_to:
        start = func.coalesce(Task.start_date, Task.due_date)
        finish = func.coalesce(Task.due_date, Task.start_date)
        conds.append(start.is_not(None))
        if query.scheduled_to:
            conds.append(start <= query.scheduled_to)
        if query.scheduled_from:
            conds.append(finish >= query.scheduled_from)
    if query.updated_since:
        conds.append(Task.updated_at >= query.updated_since)
    if query.q:
        text_q = query.q.strip()
        match = REF_PATTERN.match(text_q)
        like = "%" + text_q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        title_match = func.lower(Task.title).like(like, escape="\\")
        if match:
            conds.append(
                or_(
                    title_match,
                    and_(Project.key == match.group(1).upper(), Task.number == int(match.group(2))),
                )
            )
        else:
            conds.append(title_match)
    return stmt.where(*conds)


async def list_tasks(ctx: ServiceContext, query: TaskQuery) -> Page[TaskRead]:
    require_scope(ctx, Permission.TASK_READ)
    offset = decode_cursor(query.cursor)
    stmt = _filtered(ctx, query).order_by(*_sort_clause(query)).offset(offset).limit(query.limit + 1)
    rows = list((await ctx.session.scalars(stmt)).all())
    more = len(rows) > query.limit
    items = await _to_read(ctx, rows[: query.limit])
    return Page[TaskRead](items=items, next_cursor=encode_cursor(offset + query.limit) if more else None)


async def get_task(ctx: ServiceContext, task_id: uuid.UUID) -> TaskRead:
    task = await _load(ctx, task_id, Permission.TASK_READ, deleted=True)
    return (await _to_read(ctx, [task]))[0]


async def resolve_ref(ctx: ServiceContext, ref: str) -> uuid.UUID:
    """Resolve a task UUID or a reference like ``WEB-12`` to a task id."""
    try:
        return uuid.UUID(ref)
    except ValueError:
        pass
    match = REF_PATTERN.match(ref.strip())
    if not match:
        raise InvalidInput("expected a task id or reference like KEY-123")
    task_id = await ctx.session.scalar(
        select(Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(Project.key == match.group(1).upper(), Task.number == int(match.group(2)))
    )
    if task_id is None:
        raise NotFound("task not found")
    return task_id


# --------------------------------------------------------------------------- mutations


async def create_task(ctx: ServiceContext, data: TaskCreate) -> TaskRead:
    project = await require_project(ctx, data.project_id, Permission.TASK_CREATE)
    if project.archived_at is not None:
        raise InvalidInput("project is archived")
    status = await _status(ctx, project.id, data.status_id)
    if data.assignee_id:
        await _check_assignee(ctx, project, data.assignee_id)
    if data.parent_id:
        await _check_parent(ctx, None, project.id, data.parent_id)
    number = await ctx.session.scalar(
        update(Project)
        .where(Project.id == project.id)
        .values(task_seq=Project.task_seq + 1)
        .returning(Project.task_seq)
    )
    position = data.position
    if position is None:
        last = await ctx.session.scalar(select(func.max(Task.position)).where(Task.project_id == project.id))
        position = (last or 0) + POSITION_STEP
    from glasshaus.fields.service import merge_values

    custom = await merge_values(ctx, project.id, {}, data.custom_fields, creating=True)
    task = Task(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        number=number,
        reporter_id=ctx.actor.user_id,
        position=position,
        custom_fields=custom,
        **data.model_dump(exclude={"status_id", "position", "custom_fields"}),
    )
    _apply_status(task, status)
    ctx.session.add(task)
    await ctx.session.flush()
    await ctx.session.refresh(task)
    result = (await _to_read(ctx, [task]))[0]
    events.emit(
        ctx,
        "task.created",
        "task",
        task.id,
        {"task": result.model_dump(mode="json")},
        project_id=task.project_id,
    )
    return result


async def update_task(ctx: ServiceContext, task_id: uuid.UUID, data: TaskUpdate) -> TaskRead:
    task = await _load(ctx, task_id, Permission.TASK_UPDATE)
    if data.expected_version is not None and data.expected_version != task.version:
        raise PreconditionFailed("task was modified by someone else", extra={"current_version": task.version})
    project = await ctx.session.get(Project, task.project_id)
    assert project is not None
    changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    before = {k: getattr(task, k) for k in changes}
    if "status_id" in changes:
        if changes["status_id"] is None:
            raise InvalidInput("status_id cannot be null")
        _apply_status(task, await _status(ctx, task.project_id, changes.pop("status_id")))
    if changes.get("assignee_id"):
        await _check_assignee(ctx, project, changes["assignee_id"])
    if changes.get("parent_id"):
        await _check_parent(ctx, task, task.project_id, changes["parent_id"])
    for field in ("title", "priority"):
        if field in changes and changes[field] is None:
            raise InvalidInput(f"{field} cannot be null")
    if "tags" in changes and changes["tags"] is None:
        changes["tags"] = []
    if "custom_fields" in changes:
        from glasshaus.fields.service import merge_values

        changes["custom_fields"] = await merge_values(
            ctx, task.project_id, task.custom_fields, changes["custom_fields"] or {}
        )
    for field, value in changes.items():
        setattr(task, field, value)
    start = task.start_date
    if start and task.due_date and task.due_date < start:
        raise InvalidInput("due_date must be on or after start_date")
    try:
        await ctx.session.flush()
    except StaleDataError as exc:
        raise PreconditionFailed("task was modified concurrently") from exc
    await ctx.session.refresh(task)
    result = (await _to_read(ctx, [task]))[0]
    diff = {k: {"from": before[k], "to": getattr(task, k)} for k in before if before[k] != getattr(task, k)}
    if diff.keys() & {"start_date", "due_date"}:
        from glasshaus.scheduling.service import propagate_from

        await propagate_from(ctx, project, {task.id})
    if diff:
        events.emit(
            ctx,
            "task.updated",
            "task",
            task.id,
            {"changes": diff, "task": result.model_dump(mode="json")},
            project_id=task.project_id,
        )
    return result


async def set_done(ctx: ServiceContext, task_id: uuid.UUID, done: bool) -> TaskRead:
    """Move a task to its project's first done (or first to-do) status. Repeating it changes nothing,
    so a phone can safely replay a "done" made while offline."""
    task = await _load(ctx, task_id, Permission.TASK_UPDATE)
    status = await ctx.session.get(ProjectStatus, task.status_id)
    is_done = status is not None and status.category == StatusCategory.DONE
    if is_done == done:
        return (await _to_read(ctx, [task]))[0]
    target = await _status_in_category(
        ctx, task.project_id, StatusCategory.DONE if done else StatusCategory.TODO
    )
    return await update_task(ctx, task_id, TaskUpdate(status_id=target.id))


async def bulk_update(ctx: ServiceContext, data: TaskBulkUpdate) -> BulkResult:
    result = BulkResult(updated=[])
    patch = data.patch
    if patch.status_id and patch.status_category:
        raise InvalidInput("use either status_id or status_category, not both")
    for task_id in dict.fromkeys(data.task_ids):
        try:
            async with ctx.session.begin_nested():
                task = await _load(ctx, task_id, Permission.TASK_UPDATE)
                update_data: dict[str, Any] = patch.model_dump(
                    exclude_unset=True, exclude={"add_tags", "remove_tags", "status_category"}
                )
                if patch.status_category:
                    update_data["status_id"] = (
                        await _status_in_category(ctx, task.project_id, patch.status_category)
                    ).id
                if patch.add_tags or patch.remove_tags:
                    tags = (set(task.tags) | set(patch.add_tags)) - set(patch.remove_tags)
                    update_data["tags"] = sorted(tags)
                await update_task(ctx, task_id, TaskUpdate.model_validate(update_data))
            result.updated.append(task_id)
        except ServiceError as exc:
            result.failed[task_id] = exc.detail
    return result


async def delete_tasks(
    ctx: ServiceContext, task_ids: list[uuid.UUID], *, dry_run: bool = True
) -> list[DeletePreview]:
    """Soft-delete tasks (and their subtasks). With dry_run, report what would be deleted."""
    previews: list[DeletePreview] = []
    now = datetime.now(UTC)
    for task_id in dict.fromkeys(task_ids):
        task = await _load(ctx, task_id, Permission.TASK_DELETE)
        descendants = select(Task.id).where(Task.parent_id == task.id).cte("descendants", recursive=True)
        descendants = descendants.union_all(select(Task.id).where(Task.parent_id == descendants.c.id))
        sub_ids = list((await ctx.session.scalars(select(descendants.c.id))).all())
        previews.append(
            DeletePreview(
                resource="task", id=task.id, executed=not dry_run, affected={"subtasks": len(sub_ids)}
            )
        )
        if not dry_run:
            await ctx.session.execute(
                update(Task)
                .where(Task.id.in_([task.id, *sub_ids]), Task.deleted_at.is_(None))
                .values(deleted_at=now, version=Task.version + 1)
                .execution_options(synchronize_session=False)
            )
            events.emit(
                ctx,
                "task.deleted",
                "task",
                task.id,
                {"title": task.title, "subtasks": len(sub_ids)},
                project_id=task.project_id,
            )
    if not dry_run:
        ctx.session.expire_all()
    return previews


async def restore_task(ctx: ServiceContext, task_id: uuid.UUID) -> TaskRead:
    task = await _load(ctx, task_id, Permission.TASK_DELETE, deleted=True)
    if task.deleted_at is None:
        raise InvalidInput("task is not deleted")
    task.deleted_at = None
    await ctx.session.flush()
    events.emit(ctx, "task.restored", "task", task.id, {"title": task.title}, project_id=task.project_id)
    return await get_task(ctx, task.id)


async def can(ctx: ServiceContext, task_id: uuid.UUID) -> list[str]:
    """Permissions the actor holds on a task (lets UIs and agents hide disallowed actions)."""
    task = await _load(ctx, task_id, Permission.TASK_READ)
    project = await ctx.session.get(Project, task.project_id)
    assert project is not None
    role = await project_role(ctx, project)
    if role is None:
        raise PermissionDenied("no access")
    from glasshaus.core.rbac import scope_allows

    return sorted(p.value for p in project_role_permissions(role) if scope_allows(ctx.actor.scopes, p))
