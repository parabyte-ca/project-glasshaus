import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response, status

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
from glasshaus.people import privacy

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserRead, summary="The authenticated user")
async def get_current_user(ctx: Ctx) -> UserRead:
    return await identity.get_me(ctx)


@router.get(
    "/users/me/export",
    response_class=Response,
    summary="Download everything Glasshaus holds about you (a zip of JSON Lines files)",
)
async def export_me(ctx: Ctx) -> Response:
    assert ctx.actor.user_id is not None
    data = await privacy.export_person(ctx, ctx.actor.user_id)
    name = f"glasshaus-my-data-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


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
