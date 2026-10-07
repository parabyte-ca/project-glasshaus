import uuid

from fastapi import APIRouter, Query, status

from glasshaus.api.deps import Ctx
from glasshaus.projects import service as projects
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

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead], summary="List projects you can see")
async def list_projects(
    ctx: Ctx,
    workspace_id: uuid.UUID | None = None,
    include_archived: bool = False,
    q: str | None = Query(None, max_length=200),
) -> list[ProjectRead]:
    return await projects.list_projects(
        ctx, workspace_id=workspace_id, include_archived=include_archived, q=q
    )


@router.post(
    "", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED, summary="Create a project"
)
async def create_project(body: ProjectCreate, ctx: Ctx) -> ProjectDetail:
    return await projects.create_project(ctx, body)


@router.get("/by-key/{key}", response_model=ProjectDetail, summary="Get a project by its key")
async def get_project_by_key(key: str, ctx: Ctx) -> ProjectDetail:
    return await projects.get_project_by_key(ctx, key)


@router.get("/{project_id}", response_model=ProjectDetail, summary="Get a project with its statuses")
async def get_project(project_id: uuid.UUID, ctx: Ctx) -> ProjectDetail:
    return await projects.get_project(ctx, project_id)


@router.patch("/{project_id}", response_model=ProjectDetail, summary="Update or archive a project")
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, ctx: Ctx) -> ProjectDetail:
    return await projects.update_project(ctx, project_id, body)


@router.delete(
    "/{project_id}",
    response_model=DeletePreview,
    summary="Delete a project and its tasks (dry_run=true, the default, only previews)",
)
async def delete_project(project_id: uuid.UUID, ctx: Ctx, dry_run: bool = True) -> DeletePreview:
    return await projects.delete_project(ctx, project_id, dry_run=dry_run)


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead], summary="List project members")
async def list_project_members(project_id: uuid.UUID, ctx: Ctx) -> list[ProjectMemberRead]:
    return await projects.list_project_members(ctx, project_id)


@router.put(
    "/{project_id}/members", response_model=ProjectMemberRead, summary="Add or change a project member"
)
async def set_project_member(project_id: uuid.UUID, body: ProjectMemberSet, ctx: Ctx) -> ProjectMemberRead:
    return await projects.set_project_member(ctx, project_id, body)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project member",
)
async def remove_project_member(project_id: uuid.UUID, user_id: uuid.UUID, ctx: Ctx) -> None:
    await projects.remove_project_member(ctx, project_id, user_id)


@router.get("/{project_id}/statuses", response_model=list[StatusRead], summary="List workflow statuses")
async def list_statuses(project_id: uuid.UUID, ctx: Ctx) -> list[StatusRead]:
    return await projects.list_statuses(ctx, project_id)


@router.post(
    "/{project_id}/statuses",
    response_model=StatusRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a status",
)
async def create_status(project_id: uuid.UUID, body: StatusCreate, ctx: Ctx) -> StatusRead:
    return await projects.create_status(ctx, project_id, body)


@router.patch("/{project_id}/statuses/{status_id}", response_model=StatusRead, summary="Update a status")
async def update_status(
    project_id: uuid.UUID, status_id: uuid.UUID, body: StatusUpdate, ctx: Ctx
) -> StatusRead:
    return await projects.update_status(ctx, project_id, status_id, body)


@router.delete(
    "/{project_id}/statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a status, moving its tasks to replacement_status_id",
)
async def delete_status(
    project_id: uuid.UUID, status_id: uuid.UUID, ctx: Ctx, replacement_status_id: uuid.UUID | None = None
) -> None:
    await projects.delete_status(ctx, project_id, status_id, replacement_id=replacement_status_id)
