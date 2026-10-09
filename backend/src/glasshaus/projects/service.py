"""Project, membership and workflow-status services."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from glasshaus.core import events
from glasshaus.core.authz import project_role, require_project, require_workspace, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission, ProjectRole, WorkspaceRole
from glasshaus.identity.models import ASSISTANT_KIND, User, is_assistant
from glasshaus.projects.models import DEFAULT_STATUSES, Project, ProjectMember, ProjectStatus
from glasshaus.projects.schemas import (
    DeletePreview,
    ProjectCreate,
    ProjectDetail,
    ProjectMemberRead,
    ProjectMemberSet,
    ProjectRead,
    ProjectUpdate,
    StatusCreate,
    StatusRead,
    StatusUpdate,
)


async def _read(ctx: ServiceContext, project: Project) -> ProjectRead:
    return ProjectRead.model_validate(project).model_copy(
        update={"my_role": await project_role(ctx, project)}
    )


async def statuses_for(ctx: ServiceContext, project_id: uuid.UUID) -> list[ProjectStatus]:
    rows = await ctx.session.scalars(
        select(ProjectStatus).where(ProjectStatus.project_id == project_id).order_by(ProjectStatus.position)
    )
    return list(rows.all())


async def list_projects(
    ctx: ServiceContext,
    *,
    workspace_id: uuid.UUID | None = None,
    include_archived: bool = False,
    q: str | None = None,
) -> list[ProjectRead]:
    from glasshaus.core.authz import require_scope

    require_scope(ctx, Permission.PROJECT_READ)
    stmt = select(Project).where(visible_projects_clause(ctx)).order_by(func.lower(Project.name))
    if workspace_id:
        stmt = stmt.where(Project.workspace_id == workspace_id)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Project.name).like(like) | func.lower(Project.key).like(like))
    return [await _read(ctx, p) for p in (await ctx.session.scalars(stmt)).all()]


async def get_project(ctx: ServiceContext, project_id: uuid.UUID) -> ProjectDetail:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    base = await _read(ctx, project)
    statuses = [StatusRead.model_validate(s) for s in await statuses_for(ctx, project.id)]
    return ProjectDetail(**base.model_dump(), statuses=statuses)


async def get_project_by_key(ctx: ServiceContext, key: str) -> ProjectDetail:
    project_id = await ctx.session.scalar(select(Project.id).where(Project.key == key.upper()))
    if project_id is None:
        raise NotFound("project not found")
    return await get_project(ctx, project_id)


async def create_project(ctx: ServiceContext, data: ProjectCreate) -> ProjectDetail:
    from glasshaus.core.authz import require_scope

    require_scope(ctx, Permission.PROJECT_CREATE)
    role = await require_workspace(ctx, data.workspace_id)
    if role not in (WorkspaceRole.ADMIN, WorkspaceRole.MEMBER) or ctx.actor.org_role == OrgRole.GUEST:
        raise PermissionDenied("workspace member or admin required to create projects")
    project = Project(
        id=uuid.uuid4(), tenant_id=ctx.tenant_id, created_by=ctx.actor.user_id, **data.model_dump()
    )
    ctx.session.add(project)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict(f"project key {data.key} is already in use") from exc
    for position, (name, category, color) in enumerate(DEFAULT_STATUSES):
        ctx.session.add(
            ProjectStatus(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                name=name,
                category=category,
                color=color,
                position=float(position),
            )
        )
    if ctx.actor.user_id:
        ctx.session.add(
            ProjectMember(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                user_id=ctx.actor.user_id,
                role=ProjectRole.ADMIN,
            )
        )
    await ctx.session.flush()
    ctx.cache.pop(("project_role", project.id), None)
    result = await get_project(ctx, project.id)
    events.emit(ctx, "project.created", "project", project.id, result)
    return result


async def update_project(ctx: ServiceContext, project_id: uuid.UUID, data: ProjectUpdate) -> ProjectDetail:
    project = await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    changes = data.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    for field, value in changes.items():
        setattr(project, field, value)
    if archived is not None:
        project.archived_at = (project.archived_at or datetime.now(UTC)) if archived else None
        changes["archived"] = archived
    await ctx.session.flush()
    events.emit(ctx, "project.updated", "project", project.id, {"changes": changes})
    return await get_project(ctx, project.id)


async def delete_project(
    ctx: ServiceContext, project_id: uuid.UUID, *, dry_run: bool = True
) -> DeletePreview:
    from glasshaus.tasks.models import Task

    project = await require_project(ctx, project_id, Permission.PROJECT_DELETE)
    task_count = await ctx.session.scalar(
        select(func.count()).select_from(Task).where(Task.project_id == project_id)
    )
    preview = DeletePreview(
        resource="project", id=project.id, executed=not dry_run, affected={"tasks": task_count or 0}
    )
    if not dry_run:
        await ctx.session.delete(project)
        events.emit(ctx, "project.deleted", "project", project.id, {"key": project.key, "name": project.name})
    return preview


# --------------------------------------------------------------------------- members


async def list_project_members(ctx: ServiceContext, project_id: uuid.UUID) -> list[ProjectMemberRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    rows = await ctx.session.execute(
        select(ProjectMember.user_id, ProjectMember.role, User.kind)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
    )
    return [
        ProjectMemberRead(user_id=uid, role=role, assistant=kind == ASSISTANT_KIND)
        for uid, role, kind in rows.all()
    ]


async def set_project_member(
    ctx: ServiceContext, project_id: uuid.UUID, data: ProjectMemberSet
) -> ProjectMemberRead:
    await require_project(ctx, project_id, Permission.PROJECT_MANAGE_MEMBERS)
    user = await ctx.session.get(User, data.user_id)
    if user is None:
        raise NotFound("user not found")
    if is_assistant(user) and data.role != ProjectRole.VIEWER:
        raise InvalidInput("the project assistant can only be a viewer (set it up on the Assistant page)")
    member = await ctx.session.get(ProjectMember, (project_id, data.user_id))
    if member is None:
        member = ProjectMember(
            tenant_id=ctx.tenant_id, project_id=project_id, user_id=data.user_id, role=data.role
        )
        ctx.session.add(member)
    else:
        member.role = data.role
    await ctx.session.flush()
    events.emit(ctx, "project.member_set", "project", project_id, data)
    return ProjectMemberRead.model_validate(member)


async def remove_project_member(ctx: ServiceContext, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await require_project(ctx, project_id, Permission.PROJECT_MANAGE_MEMBERS)
    member = await ctx.session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFound("member not found")
    await ctx.session.delete(member)
    events.emit(ctx, "project.member_removed", "project", project_id, {"user_id": str(user_id)})


# --------------------------------------------------------------------------- statuses


async def list_statuses(ctx: ServiceContext, project_id: uuid.UUID) -> list[StatusRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    return [StatusRead.model_validate(s) for s in await statuses_for(ctx, project_id)]


async def create_status(ctx: ServiceContext, project_id: uuid.UUID, data: StatusCreate) -> StatusRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    position = data.position
    if position is None:
        last = await ctx.session.scalar(
            select(func.max(ProjectStatus.position)).where(ProjectStatus.project_id == project_id)
        )
        position = (last or 0) + 1
    status = ProjectStatus(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        **data.model_dump(exclude={"position"}),
        position=position,
    )
    ctx.session.add(status)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a status with this name already exists") from exc
    result = StatusRead.model_validate(status)
    events.emit(ctx, "status.created", "project", project_id, result)
    return result


async def _status(ctx: ServiceContext, project_id: uuid.UUID, status_id: uuid.UUID) -> ProjectStatus:
    status = await ctx.session.get(ProjectStatus, status_id)
    if status is None or status.project_id != project_id:
        raise NotFound("status not found")
    return status


async def update_status(
    ctx: ServiceContext, project_id: uuid.UUID, status_id: uuid.UUID, data: StatusUpdate
) -> StatusRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    status = await _status(ctx, project_id, status_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(status, field, value)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a status with this name already exists") from exc
    events.emit(
        ctx, "status.updated", "project", project_id, {"status_id": str(status_id), "changes": changes}
    )
    return StatusRead.model_validate(status)


async def delete_status(
    ctx: ServiceContext, project_id: uuid.UUID, status_id: uuid.UUID, *, replacement_id: uuid.UUID | None
) -> None:
    from sqlalchemy import update

    from glasshaus.tasks.models import Task

    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    status = await _status(ctx, project_id, status_id)
    in_use = await ctx.session.scalar(
        select(func.count()).select_from(Task).where(Task.status_id == status_id)
    )
    if in_use:
        if replacement_id is None:
            raise InvalidInput(f"{in_use} tasks use this status; provide replacement_status_id")
        replacement = await _status(ctx, project_id, replacement_id)
        if replacement.id == status.id:
            raise InvalidInput("replacement must differ from the deleted status")
        await ctx.session.execute(
            update(Task)
            .where(Task.status_id == status_id)
            .values(status_id=replacement.id, version=Task.version + 1)
        )
    remaining = await ctx.session.scalar(
        select(func.count()).select_from(ProjectStatus).where(ProjectStatus.project_id == project_id)
    )
    if (remaining or 0) <= 1:
        raise InvalidInput("a project needs at least one status")
    await ctx.session.delete(status)
    events.emit(
        ctx, "status.deleted", "project", project_id, {"status_id": str(status_id), "moved_tasks": in_use}
    )
