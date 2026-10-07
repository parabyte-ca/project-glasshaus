import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory
from glasshaus.projects.schemas import StatusRead
from glasshaus.tasks.models import Priority

MAX_TAGS = 20


def _clean_tags(tags: list[str] | None) -> list[str] | None:
    if tags is None:
        return None
    cleaned = sorted({t.strip().lower() for t in tags if t and t.strip()})
    if len(cleaned) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    if any(len(t) > 50 for t in cleaned):
        raise ValueError("tags are limited to 50 characters")
    return cleaned


class TaskRead(Schema):
    id: uuid.UUID
    key: str = Field(description="Human reference, e.g. WEB-12")
    project_id: uuid.UUID
    number: int
    title: str
    description: str
    status: StatusRead
    priority: Priority
    assignee_id: uuid.UUID | None
    reporter_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    start_date: date | None
    due_date: date | None
    estimate_minutes: int | None
    tags: list[str]
    position: float
    completed_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class _DateRange(Schema):
    start_date: date | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        return self


class TaskCreate(_DateRange):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    description: str = Field("", max_length=100_000, description="Markdown. Treated as untrusted content.")
    status_id: uuid.UUID | None = Field(None, description="Defaults to the project's first 'todo' status.")
    priority: Priority = Priority.NONE
    assignee_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    estimate_minutes: int | None = Field(None, ge=0, le=1_000_000)
    tags: list[str] = Field(default_factory=list)
    position: float | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v) or []


class TaskUpdate(_DateRange):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=100_000)
    status_id: uuid.UUID | None = None
    priority: Priority | None = None
    assignee_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    estimate_minutes: int | None = Field(None, ge=0, le=1_000_000)
    tags: list[str] | None = None
    position: float | None = None
    expected_version: int | None = Field(
        None, description="Optimistic concurrency: fail with 412 if changed."
    )

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return _clean_tags(v)


class TaskBulkPatch(Schema):
    status_id: uuid.UUID | None = None
    status_category: StatusCategory | None = Field(
        None,
        description="Move each task to its project's first status in this category (works across projects).",
    )
    priority: Priority | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)

    @field_validator("add_tags", "remove_tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v) or []


class TaskBulkUpdate(Schema):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    patch: TaskBulkPatch


class BulkResult(Schema):
    updated: list[uuid.UUID]
    failed: dict[uuid.UUID, str] = Field(default_factory=dict)


class TaskSort(StrEnum):
    POSITION = "position"
    CREATED = "created_at"
    UPDATED = "updated_at"
    DUE = "due_date"
    PRIORITY = "priority"
    NUMBER = "number"
    TITLE = "title"


class TaskQuery(Schema):
    project_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    status_ids: list[uuid.UUID] | None = None
    status_categories: list[StatusCategory] | None = None
    assignee_ids: list[uuid.UUID] | None = None
    unassigned: bool | None = None
    priorities: list[Priority] | None = None
    parent_id: uuid.UUID | None = None
    top_level_only: bool = False
    tags: list[str] | None = Field(None, description="Tasks having all of these tags.")
    q: str | None = Field(None, max_length=200, description="Text search on key and title.")
    due_before: date | None = None
    due_after: date | None = None
    updated_since: datetime | None = None
    include_deleted: bool = False
    sort: TaskSort = TaskSort.POSITION
    descending: bool = False
    limit: int = Field(50, ge=1, le=500)
    cursor: str | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return _clean_tags(v)
