"""SCIM 2.0 endpoints at /scim/v2 (bearer SCIM token; SCIM JSON and error format)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import ServiceError
from glasshaus.core.events import relay_events
from glasshaus.db import get_sessionmaker
from glasshaus.scim import service as scim
from glasshaus.scim.service import ScimError

router = APIRouter(prefix="/scim/v2", tags=["scim"])
MEDIA = "application/scim+json"


def _json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=MEDIA)


async def _ctx(request: Request) -> AsyncIterator[ServiceContext | ScimError]:
    auth = request.headers.get("authorization", "")
    async with get_sessionmaker()() as session:
        async with session.begin():
            if not auth.lower().startswith("bearer "):
                yield ScimError(401, "SCIM bearer token required")
                return
            try:
                actor = await scim.actor_from_scim_token(session, auth[7:].strip())
            except ServiceError as exc:
                yield ScimError(401, str(exc.detail))
                return
            ctx = ServiceContext(session=session, actor=actor)
            yield ctx
        if ctx.pending_events:
            await relay_events(ctx.pending_events)


Scim = Depends(_ctx, scope="function")


async def _run(
    ctx: ServiceContext | ScimError, fn: Callable[[ServiceContext], Awaitable[Any]], status: int = 200
) -> Response:
    if isinstance(ctx, ScimError):
        return _json(ctx.body(), ctx.status)
    try:
        async with ctx.session.begin_nested():  # a SCIM error undoes this request's partial changes
            result = await fn(ctx)
    except ScimError as exc:
        return _json(exc.body(), exc.status)
    if result is None:
        return Response(status_code=204)
    return _json(result, status)


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError as exc:
        raise ScimError(400, "request body is not JSON", "invalidSyntax") from exc
    if not isinstance(data, dict):
        raise ScimError(400, "request body must be a JSON object", "invalidSyntax")
    return data


@router.get("/ServiceProviderConfig", summary="SCIM service provider configuration")
async def scim_service_provider_config() -> Response:
    return _json(scim.SERVICE_PROVIDER_CONFIG)


@router.get("/ResourceTypes", summary="SCIM resource types")
async def scim_resource_types() -> Response:
    return _json(scim.list_response(scim.RESOURCE_TYPES, len(scim.RESOURCE_TYPES), 1))


@router.get("/Schemas", summary="SCIM schemas")
async def scim_schemas() -> Response:
    items = [
        {"id": scim.USER_SCHEMA, "name": "User"},
        {"id": scim.ENTERPRISE, "name": "EnterpriseUser"},
        {"id": scim.GROUP_SCHEMA, "name": "Group"},
    ]
    return _json(scim.list_response(items, len(items), 1))


@router.get("/Users", summary="List or filter users")
async def scim_list_users(
    ctx: Any = Scim,
    filter_: str | None = Query(None, alias="filter"),
    start_index: int = Query(1, alias="startIndex"),
    count: int = 100,
) -> Response:
    return await _run(ctx, lambda c: scim.list_users(c, filter_, start_index, count))


@router.post("/Users", summary="Provision a user")
async def scim_create_user(request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.create_user(c, await _body(request))

    return await _run(ctx, run, 201)


@router.get("/Users/{user_id}", summary="Get a user")
async def scim_get_user(user_id: str, ctx: Any = Scim) -> Response:
    return await _run(ctx, lambda c: scim.get_user(c, user_id))


@router.put("/Users/{user_id}", summary="Replace a user")
async def scim_replace_user(user_id: str, request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.replace_user(c, user_id, await _body(request))

    return await _run(ctx, run)


@router.patch("/Users/{user_id}", summary="Patch a user (e.g. active=false)")
async def scim_patch_user(user_id: str, request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.patch_user(c, user_id, await _body(request))

    return await _run(ctx, run)


@router.delete("/Users/{user_id}", summary="Deprovision a user (deactivates the account)")
async def scim_delete_user(user_id: str, ctx: Any = Scim) -> Response:
    return await _run(ctx, lambda c: scim.delete_user(c, user_id))


@router.get("/Groups", summary="List groups (workspaces)")
async def scim_list_groups(
    ctx: Any = Scim,
    filter_: str | None = Query(None, alias="filter"),
    start_index: int = Query(1, alias="startIndex"),
    count: int = 100,
) -> Response:
    return await _run(ctx, lambda c: scim.list_groups(c, filter_, start_index, count))


@router.post("/Groups", summary="Create a group (workspace)")
async def scim_create_group(request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.create_group(c, await _body(request))

    return await _run(ctx, run, 201)


@router.get("/Groups/{group_id}", summary="Get a group")
async def scim_get_group(group_id: str, ctx: Any = Scim) -> Response:
    return await _run(ctx, lambda c: scim.get_group(c, group_id))


@router.put("/Groups/{group_id}", summary="Replace a group's name and members")
async def scim_replace_group(group_id: str, request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.replace_group(c, group_id, await _body(request))

    return await _run(ctx, run)


@router.patch("/Groups/{group_id}", summary="Patch a group's name or members")
async def scim_patch_group(group_id: str, request: Request, ctx: Any = Scim) -> Response:
    async def run(c: ServiceContext) -> Any:
        return await scim.patch_group(c, group_id, await _body(request))

    return await _run(ctx, run)


@router.delete("/Groups/{group_id}", summary="Remove all members of a group (the workspace is kept)")
async def scim_delete_group(group_id: str, ctx: Any = Scim) -> Response:
    return await _run(ctx, lambda c: scim.delete_group(c, group_id))
