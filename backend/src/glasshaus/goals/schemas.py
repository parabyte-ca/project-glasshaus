import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from glasshaus.core.schemas import Schema
from glasshaus.insights.schemas import ProjectHealth


class KeyResultKind(StrEnum):
    METRIC = "metric"
    TASKS = "tasks"


class Confidence(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"


# --------------------------------------------------------------------------- portfolios


class PortfolioCreate(Schema):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=2000)
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class PortfolioUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    project_ids: list[uuid.UUID] | None = Field(
        None, max_length=200, description="Full replacement, in order."
    )


class PortfolioRead(Schema):
    id: uuid.UUID
    name: str
    description: str
    owner_id: uuid.UUID | None
    created_at: datetime
    project_count: int = Field(description="Projects in the portfolio that you can see.")


class PortfolioDetail(PortfolioRead):
    projects: list[ProjectHealth]
    progress: float = Field(description="Done / total across the visible projects, 0..1.")
    health: str = Field(description="Worst health among the visible projects.")


# --------------------------------------------------------------------------- OKRs


class KeyResultBase(Schema):
    title: str = Field(min_length=1, max_length=200)
    kind: KeyResultKind = KeyResultKind.METRIC
    unit: str = Field("", max_length=20, description="metric only, e.g. %, ms, users.")
    start_value: float = 0
    target_value: float = 100
    current_value: float | None = Field(None, description="metric only; defaults to start_value.")
    project_id: uuid.UUID | None = Field(
        None, description="tasks only: progress = done / total in this project."
    )
    tag: str | None = Field(None, max_length=50, description="tasks only: count only tasks with this tag.")
    weight: float = Field(1, gt=0, le=100)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == KeyResultKind.TASKS and self.project_id is None:
            raise ValueError("task-based key results need a project_id")
        if self.kind == KeyResultKind.METRIC and self.target_value == self.start_value:
            raise ValueError("target_value must differ from start_value")
        return self


class KeyResultCreate(KeyResultBase):
    pass


class KeyResultUpdate(Schema):
    title: str | None = Field(None, min_length=1, max_length=200)
    unit: str | None = Field(None, max_length=20)
    start_value: float | None = None
    target_value: float | None = None
    tag: str | None = Field(None, max_length=50)
    weight: float | None = Field(None, gt=0, le=100)


class KeyResultRead(Schema):
    id: uuid.UUID
    objective_id: uuid.UUID
    title: str
    kind: KeyResultKind
    unit: str
    start_value: float
    target_value: float
    current_value: float | None = Field(description="metric: last value; tasks: done count (null if hidden).")
    project_id: uuid.UUID | None
    tag: str | None
    weight: float
    confidence: Confidence | None
    progress: float | None = Field(description="0..1; null when the linked project is not visible to you.")
    total_tasks: int | None = None


class ObjectiveCreate(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=10_000)
    period: str = Field(
        pattern=r"^[0-9]{4}(-(Q[1-4]|H[12]|[0-9]{2}))?$", description="e.g. 2026, 2026-Q4, 2026-H1."
    )
    start_date: date | None = None
    end_date: date | None = None
    owner_id: uuid.UUID | None = Field(None, description="Defaults to you.")
    parent_id: uuid.UUID | None = Field(None, description="The objective this one supports.")
    key_results: list[KeyResultCreate] = Field(default_factory=list, max_length=10)


class ObjectiveUpdate(Schema):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=10_000)
    period: str | None = Field(None, pattern=r"^[0-9]{4}(-(Q[1-4]|H[12]|[0-9]{2}))?$")
    start_date: date | None = None
    end_date: date | None = None
    owner_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None


class ObjectiveRead(Schema):
    id: uuid.UUID
    title: str
    description: str
    period: str
    start_date: date | None
    end_date: date | None
    owner_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    created_at: datetime
    key_results: list[KeyResultRead]
    progress: float | None = Field(description="Weighted progress of the visible key results, 0..1.")
    confidence: Confidence | None = Field(description="Worst latest confidence among key results.")


class CheckInCreate(Schema):
    value: float | None = Field(None, description="New current value (metric key results).")
    confidence: Confidence
    note: str = Field("", max_length=2000)


class CheckInRead(Schema):
    id: uuid.UUID
    key_result_id: uuid.UUID
    value: float | None
    confidence: Confidence
    note: str
    author_id: uuid.UUID | None
    created_at: datetime
