import uuid
from datetime import date, datetime

from pydantic import Field

from glasshaus.core.schemas import Schema

MAX_MINUTES_PER_ENTRY = 1440


class TimeEntryCreate(Schema):
    task: str = Field(description="Task id or reference, e.g. WEB-12.")
    spent_on: date | None = Field(None, description="Day the work happened (default: today, UTC).")
    minutes: int = Field(ge=1, le=MAX_MINUTES_PER_ENTRY)
    note: str = Field("", max_length=500)
    billable: bool = False


class TimeEntryUpdate(Schema):
    spent_on: date | None = None
    minutes: int | None = Field(None, ge=1, le=MAX_MINUTES_PER_ENTRY)
    note: str | None = Field(None, max_length=500)
    billable: bool | None = None


class TimeEntryRead(Schema):
    id: uuid.UUID
    task_id: uuid.UUID
    task_key: str
    task_title: str
    project_id: uuid.UUID
    user_id: uuid.UUID
    spent_on: date
    minutes: int
    note: str
    billable: bool
    started_at: datetime | None
    created_at: datetime


class TimerStart(Schema):
    task: str = Field(description="Task id or reference.")
    note: str = Field("", max_length=500)


class TimerStop(Schema):
    spent_on: date | None = Field(
        None, description="Day to log against (default: the day the timer started)."
    )
    note: str | None = Field(None, max_length=500)
    billable: bool = False


class TimerRead(Schema):
    task_id: uuid.UUID
    task_key: str
    task_title: str
    started_at: datetime
    note: str
    elapsed_seconds: int


class TimesheetRow(Schema):
    project_id: uuid.UUID
    project_key: str
    project_name: str
    task_id: uuid.UUID
    task_key: str
    task_title: str
    minutes_by_day: dict[date, int]
    total: int


class Timesheet(Schema):
    user_id: uuid.UUID
    date_from: date
    date_to: date
    days: list[date]
    rows: list[TimesheetRow]
    totals_by_day: dict[date, int]
    total: int
    billable_total: int


class TimeReportRow(Schema):
    user_id: uuid.UUID
    user_name: str
    project_id: uuid.UUID
    project_key: str
    project_name: str
    minutes: int
    billable_minutes: int


class TimeReport(Schema):
    date_from: date
    date_to: date
    rows: list[TimeReportRow] = Field(description="One row per person and project with time in the range.")
    total: int
