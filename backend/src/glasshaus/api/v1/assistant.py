"""The AI project assistant: daily stand-up digests and weekly status drafts (read-only)."""

import uuid

from fastapi import APIRouter, Query, Response, status

from glasshaus.api.deps import Ctx, CurrentActor
from glasshaus.assistant import service as assistant
from glasshaus.assistant.schemas import (
    AssistantRead,
    AssistantStatus,
    AssistantWrite,
    BriefKind,
    BriefRead,
    BriefRun,
    BriefSummary,
)

router = APIRouter(tags=["assistant"])


@router.get(
    "/projects/{project_id}/assistant",
    response_model=AssistantStatus,
    summary="The project's assistant settings and what it can use",
)
async def get_assistant(ctx: Ctx, project_id: uuid.UUID) -> AssistantStatus:
    return await assistant.get_status(ctx, project_id)


@router.put(
    "/projects/{project_id}/assistant",
    response_model=AssistantRead,
    summary="Turn the assistant on or change it (project admins)",
)
async def set_assistant(ctx: Ctx, project_id: uuid.UUID, data: AssistantWrite) -> AssistantRead:
    return await assistant.configure(ctx, project_id, data)


@router.delete(
    "/projects/{project_id}/assistant",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Turn the assistant off and remove its settings (briefs are kept)",
)
async def delete_assistant(ctx: Ctx, project_id: uuid.UUID) -> Response:
    await assistant.remove(ctx, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/assistant/run",
    response_model=BriefRead,
    summary="Write a digest or weekly draft now (stored on the project; nobody is notified)",
)
async def run_assistant(actor: CurrentActor, project_id: uuid.UUID, data: BriefRun) -> BriefRead:
    return await assistant.run_now(actor, project_id, data.kind)


@router.get(
    "/projects/{project_id}/assistant/briefs",
    response_model=list[BriefSummary],
    summary="Digests and weekly drafts the assistant wrote, newest first",
)
async def list_briefs(
    ctx: Ctx,
    project_id: uuid.UUID,
    kind: BriefKind | None = None,
    limit: int = Query(30, ge=1, le=100),
) -> list[BriefSummary]:
    return await assistant.list_briefs(ctx, project_id, kind=kind, limit=limit)


@router.get("/assistant/briefs/{brief_id}", response_model=BriefRead, summary="One digest or weekly draft")
async def get_brief(ctx: Ctx, brief_id: uuid.UUID) -> BriefRead:
    return await assistant.get_brief(ctx, brief_id)
