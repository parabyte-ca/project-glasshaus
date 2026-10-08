"""Optional AI assistant. Read-only: results are proposals and filters, never changes."""

import uuid
from typing import Any

from fastapi import APIRouter

from glasshaus.ai import service as ai
from glasshaus.ai.service import (
    AiDraftRequest,
    AiDrafts,
    AiRisks,
    AiSearchRequest,
    AiSearchResult,
    AiStatus,
    AiStatusReport,
)
from glasshaus.api.deps import Ctx

router = APIRouter(prefix="/ai", tags=["ai"])
UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"description": "AI is not configured, turned off, or the provider failed"}
}


@router.get("/status", response_model=AiStatus, summary="Whether the AI assistant is available and enabled")
async def ai_status(ctx: Ctx) -> AiStatus:
    return await ai.get_status(ctx)


@router.post(
    "/projects/{project_id}/status-report",
    response_model=AiStatusReport,
    responses=UNAVAILABLE,
    summary="Write a status update from the project's status summary (review before sharing)",
)
async def ai_status_report(project_id: uuid.UUID, ctx: Ctx, days: int = 7) -> AiStatusReport:
    return await ai.status_report(ctx, project_id, days=days)


@router.post(
    "/projects/{project_id}/draft-tasks",
    response_model=AiDrafts,
    responses=UNAVAILABLE,
    summary="Propose tasks for a brief; nothing is created until you create them",
)
async def ai_draft_tasks(project_id: uuid.UUID, data: AiDraftRequest, ctx: Ctx) -> AiDrafts:
    return await ai.draft_tasks(ctx, project_id, data)


@router.post(
    "/projects/{project_id}/risks",
    response_model=AiRisks,
    responses=UNAVAILABLE,
    summary="Flag schedule and delivery risks with evidence and a suggested next step",
)
async def ai_risks(project_id: uuid.UUID, ctx: Ctx) -> AiRisks:
    return await ai.flag_risks(ctx, project_id)


@router.post(
    "/search",
    response_model=AiSearchResult,
    responses=UNAVAILABLE,
    summary="Search tasks in plain words; returns the filters used and the matching tasks",
)
async def ai_search(data: AiSearchRequest, ctx: Ctx) -> AiSearchResult:
    return await ai.search(ctx, data)
