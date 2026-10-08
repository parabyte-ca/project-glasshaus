import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory

Bucket = Literal["day", "week"]
Health = Literal["on_track", "at_risk", "off_track"]


# --------------------------------------------------------------------------- workload


class WorkloadBucket(Schema):
    start: date
    capacity: int = Field(description="Available minutes in this bucket (within the range).")
    planned: int = Field(description="Remaining estimated work scheduled in this bucket.")
    logged: int = Field(description="Minutes logged in this bucket.")


class WorkloadUser(Schema):
    user_id: uuid.UUID
    name: str
    capacity_minutes: int
    working_days: list[int]
    buckets: list[WorkloadBucket]
    capacity_total: int
    planned_total: int
    logged_total: int
    utilization: float | None = Field(description="planned / capacity over the range; null without capacity.")
    overloaded_buckets: int
    open_tasks: int
    unestimated_tasks: int
    unscheduled_minutes: int = Field(description="Remaining work on tasks with no dates.")
    overdue_minutes: int = Field(description="Remaining work on tasks due before the range.")


class Workload(Schema):
    date_from: date
    date_to: date
    bucket: Bucket
    buckets: list[date]
    users: list[WorkloadUser]


# --------------------------------------------------------------------------- project report


class StatusCount(Schema):
    status_id: uuid.UUID
    name: str
    category: StatusCategory
    color: str
    count: int


class AssigneeLoad(Schema):
    user_id: uuid.UUID | None
    open_tasks: int
    remaining_minutes: int


class BurnupPoint(Schema):
    day: date
    scope: int
    done: int


class ThroughputPoint(Schema):
    week: date
    completed: int


class TimeSummary(Schema):
    median: float | None
    p85: float | None
    average: float | None


class ProjectReport(Schema):
    project_id: uuid.UUID
    date_from: date
    date_to: date
    total: int
    open: int
    done: int
    overdue: int
    by_status: list[StatusCount]
    by_assignee: list[AssigneeLoad]
    by_priority: dict[str, int] = Field(description="Open tasks per priority.")
    burnup: list[BurnupPoint]
    throughput: list[ThroughputPoint] = Field(description="Tasks completed per week (Monday).")
    lead_time_days: TimeSummary = Field(description="Created → completed, for tasks completed in the range.")
    estimate_minutes: int = Field(description="Estimates of tasks completed in the range.")
    actual_minutes: int = Field(description="Time logged on tasks completed in the range.")
    logged_minutes: int = Field(description="All time logged on the project in the range.")


class ProjectHealth(Schema):
    project_id: uuid.UUID
    key: str
    name: str
    total: int
    done: int
    progress: float = Field(description="Done / (total - cancelled), 0..1.")
    overdue: int
    finish: date | None = Field(description="Latest due date of open work.")
    slip_days: int = Field(description="Finish behind the latest baseline (0 without one).")
    logged_minutes: int
    health: Health


# --------------------------------------------------------------------------- dashboards

WidgetType = Literal[
    "my_tasks",
    "my_time",
    "project_status",
    "burnup",
    "throughput",
    "workload",
    "time_by_project",
    "portfolio",
    "objective",
]


class Widget(Schema):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    type: WidgetType
    title: str = Field("", max_length=100)
    width: int = Field(1, ge=1, le=3, description="Columns spanned in a 3-column grid.")
    config: dict[str, Any] = Field(
        default_factory=dict, description="project_id, portfolio_id or objective_id, depending on the type."
    )


class DashboardCreate(Schema):
    name: str = Field(min_length=1, max_length=100)
    shared: bool = Field(False, description="Visible to everyone in the organization (not guests).")
    widgets: list[Widget] = Field(default_factory=list, max_length=24)


class DashboardUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    shared: bool | None = None
    widgets: list[Widget] | None = Field(None, max_length=24)


class DashboardRead(DashboardCreate):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
