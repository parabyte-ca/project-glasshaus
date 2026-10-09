import re
import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from glasshaus.api.deps import Ctx, CurrentActor
from glasshaus.reports import service as reports
from glasshaus.reports import subscriptions
from glasshaus.reports.schemas import (
    ReportDefinition,
    ReportEmailStatus,
    ReportOverrides,
    ReportResult,
    ReportSubscriptionRead,
    ReportSubscriptionWrite,
    SavedReportCreate,
    SavedReportRead,
    SavedReportUpdate,
)

router = APIRouter(tags=["reports"])
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}


@router.post(
    "/reports/run",
    response_model=ReportResult,
    summary="Run a report definition without saving it (the report builder's preview)",
)
async def run_definition(definition: ReportDefinition, ctx: Ctx) -> ReportResult:
    return await reports.run_definition(ctx, definition)


@router.get("/reports", response_model=list[SavedReportRead], summary="Your and shared saved reports")
async def list_reports(ctx: Ctx) -> list[SavedReportRead]:
    return await reports.list_reports(ctx)


@router.post(
    "/reports", response_model=SavedReportRead, status_code=status.HTTP_201_CREATED, summary="Save a report"
)
async def create_report(data: SavedReportCreate, ctx: Ctx) -> SavedReportRead:
    return await reports.create_report(ctx, data)


@router.get(
    "/reports/subscriptions",
    response_model=list[ReportSubscriptionRead],
    summary="Your report emails",
)
async def list_report_emails(ctx: Ctx) -> list[ReportSubscriptionRead]:
    return await subscriptions.list_subscriptions(ctx)


@router.get("/reports/{report_id}", response_model=SavedReportRead, summary="A saved report's definition")
async def get_report(report_id: uuid.UUID, ctx: Ctx) -> SavedReportRead:
    return await reports.get_report(ctx, report_id)


@router.patch(
    "/reports/{report_id}", response_model=SavedReportRead, summary="Rename, share or change a saved report"
)
async def update_report(report_id: uuid.UUID, data: SavedReportUpdate, ctx: Ctx) -> SavedReportRead:
    return await reports.update_report(ctx, report_id, data)


@router.delete(
    "/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a saved report"
)
async def delete_report(report_id: uuid.UUID, ctx: Ctx) -> Response:
    await reports.delete_report(ctx, report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/reports/{report_id}/run",
    response_model=ReportResult,
    summary="Run a saved report with your access, optionally with dashboard filters",
)
async def run_report(
    report_id: uuid.UUID, ctx: Ctx, overrides: ReportOverrides | None = None
) -> ReportResult:
    return await reports.run_report(ctx, report_id, overrides)


@router.get(
    "/reports/{report_id}/export",
    response_class=Response,
    responses=CSV,
    summary="Download a saved report as CSV (up to 500 rows)",
)
async def export_report(report_id: uuid.UUID, ctx: Ctx) -> Response:
    name, body = await reports.export_report(ctx, report_id)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "report"
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="glasshaus-{filename}.csv"'},
    )


@router.get(
    "/reports/{report_id}/email",
    response_model=ReportEmailStatus,
    summary="Whether email is available and your email schedule for this report",
)
async def report_email_status(report_id: uuid.UUID, ctx: Ctx) -> ReportEmailStatus:
    return await subscriptions.email_status(ctx, report_id)


@router.put(
    "/reports/{report_id}/email",
    response_model=ReportSubscriptionRead,
    summary="Email this report to yourself on a schedule (runs with your access each time)",
    responses={503: {"description": "Email is not configured on this server"}},
)
async def subscribe_report(
    report_id: uuid.UUID, data: ReportSubscriptionWrite, ctx: Ctx
) -> ReportSubscriptionRead:
    return await subscriptions.subscribe(ctx, report_id, data)


@router.delete(
    "/reports/{report_id}/email",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop emailing this report to you",
)
async def unsubscribe_report(report_id: uuid.UUID, ctx: Ctx) -> Response:
    await subscriptions.unsubscribe(ctx, report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/reports/{report_id}/email/send",
    response_model=dict[str, str],
    summary="Email this report to yourself now",
    responses={503: {"description": "Email is not configured or delivery failed"}},
)
async def send_report_now(
    report_id: uuid.UUID, actor: CurrentActor, attach_csv: bool = True
) -> dict[str, str]:
    return {"sent_to": await subscriptions.send_now(actor, report_id, attach_csv=attach_csv)}
