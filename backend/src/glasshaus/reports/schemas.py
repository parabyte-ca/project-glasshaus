"""Report definitions and results.

A definition only names things from fixed lists (sources, groupings, measures, filters), so a report
can never express arbitrary SQL. Custom-field groupings are written ``cf:<field id>``.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory
from glasshaus.tasks.models import Priority

Source = Literal["tasks", "time"]

TASK_DIMENSIONS = (
    "project",
    "status",
    "status_category",
    "priority",
    "assignee",
    "reporter",
    "tag",
    "due_week",
    "due_month",
    "created_week",
    "created_month",
    "completed_week",
    "completed_month",
)
TIME_DIMENSIONS = ("project", "person", "task", "day", "week", "month", "billable")
TASK_MEASURES = (
    "count",
    "open",
    "done",
    "overdue",
    "estimate_hours",
    "avg_age_days",
    "avg_cycle_days",
    "on_time_pct",
)
TIME_MEASURES = ("hours", "billable_hours", "entries", "people")
CUSTOM_FIELD_PREFIX = "cf:"

Measure = Literal[
    "count",
    "open",
    "done",
    "overdue",
    "estimate_hours",
    "avg_age_days",
    "avg_cycle_days",
    "on_time_pct",
    "hours",
    "billable_hours",
    "entries",
    "people",
]
DatePreset = Literal[
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_month",
    "last_month",
    "this_quarter",
    "this_year",
    "next_30_days",
    "custom",
]
DateField = Literal["created", "completed", "due", "spent"]
Chart = Literal["table", "bar", "line", "kpi"]


class DateFilter(Schema):
    field: DateField = Field(
        "created", description="Tasks: created, completed or due. Time: always the day the time was spent."
    )
    preset: DatePreset = "last_30_days"
    date_from: date | None = Field(None, description="With preset=custom.")
    date_to: date | None = Field(None, description="With preset=custom.")

    @model_validator(mode="after")
    def _custom_needs_dates(self) -> "DateFilter":
        if self.preset == "custom":
            if self.date_from is None or self.date_to is None:
                raise ValueError("a custom date range needs date_from and date_to")
            if self.date_from > self.date_to:
                raise ValueError("date_from must be on or before date_to")
        return self


class ReportFilters(Schema):
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    status_categories: list[StatusCategory] = Field(default_factory=list, description="Tasks only.")
    priorities: list[Priority] = Field(default_factory=list, description="Tasks only.")
    people: list[uuid.UUID] = Field(
        default_factory=list, max_length=100, description="Tasks: assignee. Time: who logged it."
    )
    tags: list[str] = Field(default_factory=list, max_length=20, description="Tasks only (any of).")
    billable: bool | None = Field(None, description="Time only.")
    date: DateFilter | None = None


class SortSpec(Schema):
    by: str = Field("label", description='"label" or one of the report\'s measures.', max_length=40)
    descending: bool = False


class ReportDefinition(Schema):
    source: Source = "tasks"
    group_by: list[str] = Field(default_factory=list, max_length=2, description="Up to two groupings.")
    measures: list[Measure] = Field(
        default_factory=list, max_length=6, description="Default: count (tasks) or hours (time)."
    )
    filters: ReportFilters = Field(default_factory=ReportFilters)
    chart: Chart = "table"
    sort: SortSpec = Field(default_factory=SortSpec)
    limit: int = Field(50, ge=1, le=500, description="Rows shown (the rest are counted in the totals).")

    @model_validator(mode="after")
    def _consistent(self) -> "ReportDefinition":
        dims = TASK_DIMENSIONS if self.source == "tasks" else TIME_DIMENSIONS
        measures = TASK_MEASURES if self.source == "tasks" else TIME_MEASURES
        if not self.measures:
            self.measures = ["count" if self.source == "tasks" else "hours"]
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("each grouping can be used once")
        for dim in self.group_by:
            custom = self.source == "tasks" and dim.startswith(CUSTOM_FIELD_PREFIX)
            if custom:
                try:
                    uuid.UUID(dim.removeprefix(CUSTOM_FIELD_PREFIX))
                except ValueError as exc:
                    raise ValueError(f"unknown custom field grouping {dim!r}") from exc
            elif dim not in dims:
                raise ValueError(f"{dim!r} is not a grouping for {self.source} reports")
        for m in self.measures:
            if m not in measures:
                raise ValueError(f"{m!r} is not a measure for {self.source} reports")
        if len(set(self.measures)) != len(self.measures):
            raise ValueError("each measure can be used once")
        if self.sort.by != "label" and self.sort.by not in self.measures:
            raise ValueError("sort by 'label' or one of the report's measures")
        f = self.filters
        if self.source == "time" and (f.status_categories or f.priorities or f.tags):
            raise ValueError("status, priority and tag filters apply to task reports")
        if self.source == "tasks" and f.billable is not None:
            raise ValueError("the billable filter applies to time reports")
        if f.date is not None:
            if self.source == "time" and f.date.field != "spent":
                raise ValueError("time reports filter on the day time was spent (field 'spent')")
            if self.source == "tasks" and f.date.field == "spent":
                raise ValueError("task reports filter on created, completed or due")
        return self


class ReportOverrides(Schema):
    """Dashboard-wide filters applied on top of a saved report when it runs as a tile."""

    date: DateFilter | None = Field(None, description="Replaces the report's own date range.")
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class Column(Schema):
    key: str
    label: str
    kind: Literal["dimension", "measure"]
    unit: Literal["text", "date", "count", "hours", "days", "percent"]


class Row(Schema):
    keys: list[str | None] = Field(description="Raw grouping values (ids, dates), for linking.")
    labels: list[str]
    values: list[float | None]


class ReportResult(Schema):
    columns: list[Column]
    rows: list[Row]
    totals: list[float | None]
    total_groups: int = Field(description="Groups before the row limit.")
    truncated: bool
    date_from: date | None
    date_to: date | None
    generated_at: datetime


class SavedReportCreate(Schema):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    shared: bool = Field(False, description="Visible to everyone in the organization (not guests).")
    definition: ReportDefinition


class SavedReportUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    shared: bool | None = None
    definition: ReportDefinition | None = None


class SavedReportRead(Schema):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    name: str
    description: str
    shared: bool
    definition: ReportDefinition
    created_at: datetime
    updated_at: datetime
