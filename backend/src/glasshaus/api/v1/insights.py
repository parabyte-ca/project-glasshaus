import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Response, status

from glasshaus.api.deps import Ctx
from glasshaus.insights import service as insights
from glasshaus.insights.schemas import (
    Bucket,
    DashboardCreate,
    DashboardRead,
    DashboardUpdate,
    ProjectHealth,
    ProjectReport,
    StatusSummary,
    Workload,
)

router = APIRouter()
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}


@router.get(
    "/workload",
    response_model=Workload,
    tags=["reports"],
    summary="Planned work vs capacity per person (default: 4 weeks from this Monday)",
)
async def get_workload(
    ctx: Ctx,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    bucket: Bucket = "week",
) -> Workload:
    return await insights.workload(
        ctx,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        workspace_id=workspace_id,
        bucket=bucket,
    )


@router.get(
    "/projects/{project_id}/report",
    response_model=ProjectReport,
    tags=["reports"],
    summary="Status mix, burn-up, throughput, lead time and estimate vs actual (default: last 30 days)",
)
async def project_report(
    project_id: uuid.UUID, ctx: Ctx, date_from: date | None = None, date_to: date | None = None
) -> ProjectReport:
    return await insights.project_report(ctx, project_id, date_from=date_from, date_to=date_to)


@router.get(
    "/projects/{project_id}/status-summary",
    response_model=StatusSummary,
    tags=["reports"],
    summary="Data for a status update: done, in progress, overdue, due soon, warnings (default: 7 days)",
)
async def status_summary(project_id: uuid.UUID, ctx: Ctx, days: int = 7) -> StatusSummary:
    return await insights.status_summary(ctx, project_id, days=days)


@router.get(
    "/projects/{project_id}/health",
    response_model=ProjectHealth,
    tags=["reports"],
    summary="Progress, overdue work, baseline slip and a health rating",
)
async def project_health(project_id: uuid.UUID, ctx: Ctx) -> ProjectHealth:
    return await insights.get_project_health(ctx, project_id)


@router.get(
    "/projects/{project_id}/tasks/export",
    response_class=Response,
    responses=CSV,
    tags=["reports"],
    summary="Export the project's tasks as CSV",
)
async def export_tasks(project_id: uuid.UUID, ctx: Ctx) -> Response:
    body = await insights.export_tasks_csv(ctx, project_id)
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="glasshaus-tasks.csv"'},
    )


@router.get(
    "/dashboards",
    response_model=list[DashboardRead],
    tags=["dashboards"],
    summary="Your and shared dashboards",
)
async def list_dashboards(ctx: Ctx) -> list[DashboardRead]:
    return await insights.list_dashboards(ctx)


@router.post(
    "/dashboards",
    response_model=DashboardRead,
    status_code=status.HTTP_201_CREATED,
    tags=["dashboards"],
    summary="Create a dashboard",
)
async def create_dashboard(body: DashboardCreate, ctx: Ctx) -> DashboardRead:
    return await insights.create_dashboard(ctx, body)


@router.get(
    "/dashboards/{dashboard_id}", response_model=DashboardRead, tags=["dashboards"], summary="Get a dashboard"
)
async def get_dashboard(dashboard_id: uuid.UUID, ctx: Ctx) -> DashboardRead:
    return await insights.get_dashboard(ctx, dashboard_id)


@router.patch(
    "/dashboards/{dashboard_id}",
    response_model=DashboardRead,
    tags=["dashboards"],
    summary="Change a dashboard",
)
async def update_dashboard(dashboard_id: uuid.UUID, body: DashboardUpdate, ctx: Ctx) -> DashboardRead:
    return await insights.update_dashboard(ctx, dashboard_id, body)


@router.delete(
    "/dashboards/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["dashboards"],
    summary="Delete a dashboard",
)
async def delete_dashboard(dashboard_id: uuid.UUID, ctx: Ctx) -> None:
    await insights.delete_dashboard(ctx, dashboard_id)
