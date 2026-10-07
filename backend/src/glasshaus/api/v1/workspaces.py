import uuid

from fastapi import APIRouter, status

from glasshaus.api.deps import Ctx
from glasshaus.identity import service as identity
from glasshaus.identity.schemas import (
    WorkspaceCreate,
    WorkspaceMemberRead,
    WorkspaceMemberSet,
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead], summary="List workspaces you can see")
async def list_workspaces(ctx: Ctx) -> list[WorkspaceRead]:
    return await identity.list_workspaces(ctx)


@router.post(
    "", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED, summary="Create a workspace"
)
async def create_workspace(body: WorkspaceCreate, ctx: Ctx) -> WorkspaceRead:
    return await identity.create_workspace(ctx, body)


@router.get("/{workspace_id}", response_model=WorkspaceRead, summary="Get a workspace")
async def get_workspace(workspace_id: uuid.UUID, ctx: Ctx) -> WorkspaceRead:
    return await identity.get_workspace(ctx, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceRead, summary="Update a workspace")
async def update_workspace(workspace_id: uuid.UUID, body: WorkspaceUpdate, ctx: Ctx) -> WorkspaceRead:
    return await identity.update_workspace(ctx, workspace_id, body)


@router.get(
    "/{workspace_id}/members", response_model=list[WorkspaceMemberRead], summary="List workspace members"
)
async def list_workspace_members(workspace_id: uuid.UUID, ctx: Ctx) -> list[WorkspaceMemberRead]:
    return await identity.list_workspace_members(ctx, workspace_id)


@router.put("/{workspace_id}/members", response_model=WorkspaceMemberRead, summary="Add or change a member")
async def set_workspace_member(
    workspace_id: uuid.UUID, body: WorkspaceMemberSet, ctx: Ctx
) -> WorkspaceMemberRead:
    return await identity.set_workspace_member(ctx, workspace_id, body)


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a member"
)
async def remove_workspace_member(workspace_id: uuid.UUID, user_id: uuid.UUID, ctx: Ctx) -> None:
    await identity.remove_workspace_member(ctx, workspace_id, user_id)
