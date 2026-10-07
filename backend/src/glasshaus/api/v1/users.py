import uuid

from fastapi import APIRouter, Query, status

from glasshaus.api.deps import Ctx
from glasshaus.identity import service as identity
from glasshaus.identity.schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserRead, summary="The authenticated user")
async def get_current_user(ctx: Ctx) -> UserRead:
    return await identity.get_me(ctx)


@router.get("/users", response_model=list[UserRead], summary="List users in the organization")
async def list_users(
    ctx: Ctx, q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500)
) -> list[UserRead]:
    return await identity.list_users(ctx, q=q, limit=limit)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Create a user")
async def create_user(body: UserCreate, ctx: Ctx) -> UserRead:
    return await identity.create_user(ctx, body)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Update a user's name, role or status")
async def update_user(user_id: uuid.UUID, body: UserUpdate, ctx: Ctx) -> UserRead:
    return await identity.update_user(ctx, user_id, body)


@router.get("/tokens", response_model=list[ApiTokenRead], tags=["tokens"], summary="List your API tokens")
async def list_api_tokens(ctx: Ctx) -> list[ApiTokenRead]:
    return await identity.list_api_tokens(ctx)


@router.post(
    "/tokens",
    response_model=ApiTokenCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["tokens"],
    summary="Create an API token (the secret is returned once)",
)
async def create_api_token(body: ApiTokenCreate, ctx: Ctx) -> ApiTokenCreated:
    return await identity.create_api_token(ctx, body)


@router.delete(
    "/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["tokens"], summary="Revoke a token"
)
async def revoke_api_token(token_id: uuid.UUID, ctx: Ctx) -> None:
    await identity.revoke_api_token(ctx, token_id)
