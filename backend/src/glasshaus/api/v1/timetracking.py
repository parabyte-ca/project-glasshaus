import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from glasshaus.api.deps import Ctx
from glasshaus.core.schemas import Page
from glasshaus.timetracking import service as timetracking
from glasshaus.timetracking.schemas import (
    TimeEntryCreate,
    TimeEntryRead,
    TimeEntryUpdate,
    TimeReport,
    TimerRead,
    TimerStart,
    TimerStop,
    Timesheet,
)

router = APIRouter(tags=["time"])
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}, "description": "CSV file"}}


@router.get("/time-entries", response_model=Page[TimeEntryRead], summary="List time entries")
async def list_entries(
    ctx: Ctx,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    task: Annotated[str | None, Query(description="Task id or reference")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: str | None = None,
) -> Page[TimeEntryRead]:
    return await timetracking.list_entries(
        ctx,
        user_id=user_id,
        project_id=project_id,
        task=task,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/time-entries/export",
    response_class=Response,
    responses=CSV,
    summary="Export time entries as CSV (default: last 31 days)",
)
async def export_entries(
    ctx: Ctx,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    body = await timetracking.export_csv(
        ctx, user_id=user_id, project_id=project_id, date_from=date_from, date_to=date_to
    )
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="glasshaus-time.csv"'},
    )


@router.post(
    "/time-entries",
    response_model=TimeEntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log time on a task",
)
async def log_time(body: TimeEntryCreate, ctx: Ctx) -> TimeEntryRead:
    return await timetracking.log_time(ctx, body)


@router.patch("/time-entries/{entry_id}", response_model=TimeEntryRead, summary="Change a time entry")
async def update_entry(entry_id: uuid.UUID, body: TimeEntryUpdate, ctx: Ctx) -> TimeEntryRead:
    return await timetracking.update_entry(ctx, entry_id, body)


@router.delete(
    "/time-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a time entry"
)
async def delete_entry(entry_id: uuid.UUID, ctx: Ctx) -> None:
    await timetracking.delete_entry(ctx, entry_id)


@router.get("/timer", response_model=TimerRead | None, summary="Your running timer (null when none)")
async def get_timer(ctx: Ctx) -> TimerRead | None:
    return await timetracking.get_timer(ctx)


@router.post("/timer", response_model=TimerRead, status_code=status.HTTP_201_CREATED, summary="Start a timer")
async def start_timer(body: TimerStart, ctx: Ctx) -> TimerRead:
    return await timetracking.start_timer(ctx, body)


@router.post("/timer/stop", response_model=TimeEntryRead, summary="Stop the timer and log the time")
async def stop_timer(body: TimerStop, ctx: Ctx) -> TimeEntryRead:
    return await timetracking.stop_timer(ctx, body)


@router.delete("/timer", status_code=status.HTTP_204_NO_CONTENT, summary="Discard the running timer")
async def discard_timer(ctx: Ctx) -> None:
    await timetracking.discard_timer(ctx)


@router.get(
    "/timesheets",
    response_model=Timesheet,
    summary="A person's time per task and day (default: you, last 7 days)",
)
async def get_timesheet(
    ctx: Ctx, user_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None
) -> Timesheet:
    return await timetracking.timesheet(ctx, user_id, date_from, date_to)


@router.get(
    "/reports/time",
    response_model=TimeReport,
    summary="Minutes per person and project (default: last 30 days)",
)
async def time_report(
    ctx: Ctx,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> TimeReport:
    return await timetracking.time_report(
        ctx, date_from=date_from, date_to=date_to, project_id=project_id, user_id=user_id
    )
