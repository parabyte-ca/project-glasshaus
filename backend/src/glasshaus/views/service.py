"""Saved views: named filter/group/sort/column configurations over a project's tasks."""

import uuid

from sqlalchemy import func, or_, select

from glasshaus.core import events
from glasshaus.core.authz import require_project, require_scope
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import NotFound, PermissionDenied
from glasshaus.core.rbac import Permission
from glasshaus.core.schemas import Page
from glasshaus.tasks import service as tasks
from glasshaus.tasks.schemas import TaskQuery, TaskRead
from glasshaus.views.models import SavedView
from glasshaus.views.schemas import ViewCreate, ViewRead, ViewUpdate


async def list_views(ctx: ServiceContext, project_id: uuid.UUID) -> list[ViewRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    rows = await ctx.session.scalars(
        select(SavedView)
        .where(
            SavedView.project_id == project_id,
            or_(SavedView.shared.is_(True), SavedView.owner_id == ctx.actor.user_id),
        )
        .order_by(SavedView.position, SavedView.name)
    )
    return [ViewRead.model_validate(v) for v in rows.all()]


async def create_view(ctx: ServiceContext, project_id: uuid.UUID, data: ViewCreate) -> ViewRead:
    require_scope(ctx, Permission.TASK_UPDATE)  # a read-only token changes nothing
    await require_project(
        ctx, project_id, Permission.PROJECT_UPDATE if data.shared else Permission.PROJECT_READ
    )
    if ctx.actor.user_id is None and not data.shared:
        raise PermissionDenied("personal views need a user principal")
    position = data.position
    if position is None:
        last = await ctx.session.scalar(
            select(func.max(SavedView.position)).where(SavedView.project_id == project_id)
        )
        position = (last or 0) + 1
    view = SavedView(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        owner_id=ctx.actor.user_id,
        name=data.name,
        kind=data.kind,
        shared=data.shared,
        config=data.config.model_dump(mode="json"),
        position=position,
    )
    ctx.session.add(view)
    await ctx.session.flush()
    result = ViewRead.model_validate(view)
    if view.shared:
        events.emit(ctx, "view.created", "project", project_id, {"view_id": str(view.id), "name": view.name})
    return result


async def _editable(ctx: ServiceContext, view_id: uuid.UUID, *, sharing: bool = False) -> SavedView:
    require_scope(ctx, Permission.TASK_UPDATE)
    view = await ctx.session.get(SavedView, view_id)
    if view is None:
        raise NotFound("view not found")
    await require_project(ctx, view.project_id, Permission.PROJECT_READ)
    if not view.shared and view.owner_id != ctx.actor.user_id:
        raise NotFound("view not found")
    if view.shared or sharing:
        await require_project(ctx, view.project_id, Permission.PROJECT_UPDATE)
    return view


async def get_view(ctx: ServiceContext, view_id: uuid.UUID) -> ViewRead:
    view = await ctx.session.get(SavedView, view_id)
    if view is None or (not view.shared and view.owner_id != ctx.actor.user_id):
        raise NotFound("view not found")
    await require_project(ctx, view.project_id, Permission.PROJECT_READ)
    return ViewRead.model_validate(view)


async def update_view(ctx: ServiceContext, view_id: uuid.UUID, data: ViewUpdate) -> ViewRead:
    view = await _editable(ctx, view_id, sharing=bool(data.shared))
    changes = data.model_dump(exclude_unset=True, mode="json")
    for key, value in changes.items():
        setattr(view, key, value)
    await ctx.session.flush()
    if view.shared:
        events.emit(
            ctx, "view.updated", "project", view.project_id, {"view_id": str(view.id), "name": view.name}
        )
    return ViewRead.model_validate(view)


async def delete_view(ctx: ServiceContext, view_id: uuid.UUID) -> None:
    view = await _editable(ctx, view_id)
    await ctx.session.delete(view)
    if view.shared:
        events.emit(
            ctx, "view.deleted", "project", view.project_id, {"view_id": str(view.id), "name": view.name}
        )


async def run_view(
    ctx: ServiceContext, view_id: uuid.UUID, *, limit: int = 200, cursor: str | None = None
) -> Page[TaskRead]:
    """Execute a saved view's filters and sort (grouping and columns are presentation)."""
    view = await get_view(ctx, view_id)
    cfg = view.config
    query = TaskQuery(
        project_id=view.project_id,
        **cfg.filters.model_dump(exclude_none=True),
        sort=cfg.sort,
        descending=cfg.descending,
        sort_field=cfg.sort_field,
        limit=limit,
        cursor=cursor,
    )
    return await tasks.list_tasks(ctx, query)
