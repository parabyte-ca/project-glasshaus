import uuid

from fastapi import APIRouter, Query, status

from glasshaus.api.deps import Ctx
from glasshaus.core.schemas import Page
from glasshaus.tasks.schemas import TaskRead
from glasshaus.views import service as views
from glasshaus.views.schemas import ViewCreate, ViewRead, ViewUpdate

router = APIRouter(tags=["views"])


@router.get(
    "/projects/{project_id}/views", response_model=list[ViewRead], summary="Shared and your own views"
)
async def list_views(project_id: uuid.UUID, ctx: Ctx) -> list[ViewRead]:
    return await views.list_views(ctx, project_id)


@router.post(
    "/projects/{project_id}/views",
    response_model=ViewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save a view",
)
async def create_view(project_id: uuid.UUID, body: ViewCreate, ctx: Ctx) -> ViewRead:
    return await views.create_view(ctx, project_id, body)


@router.get("/views/{view_id}", response_model=ViewRead, summary="Get a saved view")
async def get_view(view_id: uuid.UUID, ctx: Ctx) -> ViewRead:
    return await views.get_view(ctx, view_id)


@router.patch("/views/{view_id}", response_model=ViewRead, summary="Update a saved view")
async def update_view(view_id: uuid.UUID, body: ViewUpdate, ctx: Ctx) -> ViewRead:
    return await views.update_view(ctx, view_id, body)


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a saved view")
async def delete_view(view_id: uuid.UUID, ctx: Ctx) -> None:
    await views.delete_view(ctx, view_id)


@router.get("/views/{view_id}/tasks", response_model=Page[TaskRead], summary="Run a saved view")
async def run_view(
    view_id: uuid.UUID, ctx: Ctx, limit: int = Query(200, ge=1, le=500), cursor: str | None = None
) -> Page[TaskRead]:
    return await views.run_view(ctx, view_id, limit=limit, cursor=cursor)
