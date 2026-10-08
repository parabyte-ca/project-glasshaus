import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from glasshaus.core.schemas import Schema
from glasshaus.scheduling.models import DependencyType


class DependencyCreate(Schema):
    predecessor: str = Field(description="Task id or reference (e.g. WEB-3) that must happen first.")
    successor: str = Field(description="Task id or reference that depends on the predecessor.")
    type: DependencyType = DependencyType.FINISH_TO_START
    lag_days: int = Field(0, ge=-365, le=365, description="Gap in days; negative for a lead.")


class DependencyUpdate(Schema):
    type: DependencyType | None = None
    lag_days: int | None = Field(None, ge=-365, le=365)


class DependencyRead(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    predecessor_id: uuid.UUID
    predecessor_key: str
    predecessor_title: str
    successor_id: uuid.UUID
    successor_key: str
    successor_title: str
    type: DependencyType
    lag_days: int
    created_at: datetime


class TaskMove(Schema):
    task_id: uuid.UUID
    key: str
    start_date: date | None
    due_date: date | None
    new_start_date: date | None
    new_due_date: date | None
    days: int = Field(description="How many days later the task now is.")


class DependencyResult(Schema):
    dependency: DependencyRead
    rescheduled: list[TaskMove] = Field(description="Tasks moved by auto-scheduling (empty when it is off).")


class TaskDependencies(Schema):
    predecessors: list[DependencyRead]
    successors: list[DependencyRead]


class ScheduledTask(Schema):
    task_id: uuid.UUID
    key: str
    title: str
    start_date: date
    due_date: date
    early_start: date
    early_finish: date
    late_start: date
    late_finish: date
    slack_days: int
    critical: bool


class ScheduleRead(Schema):
    project_id: uuid.UUID
    project_start: date | None
    project_finish: date | None
    tasks: list[ScheduledTask]
    critical_path: list[uuid.UUID] = Field(description="Critical tasks in schedule order.")
    unscheduled: list[uuid.UUID] = Field(description="Tasks without dates (excluded from the calculation).")
    dependencies: list[DependencyRead]


class RescheduleResult(Schema):
    executed: bool
    moves: list[TaskMove]


class BaselineCreate(Schema):
    name: str = Field(min_length=1, max_length=100)


class BaselineRead(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    created_by: uuid.UUID | None
    created_at: datetime
    task_count: int


class TaskVariance(Schema):
    task_id: uuid.UUID
    key: str
    title: str
    baseline_start: date | None
    baseline_due: date | None
    start_date: date | None
    due_date: date | None
    start_variance_days: int | None = Field(description="Positive = later than the baseline.")
    finish_variance_days: int | None


class BaselineVariance(Schema):
    baseline: BaselineRead
    tasks: list[TaskVariance]
    baseline_finish: date | None
    current_finish: date | None
    finish_variance_days: int | None


class WarningKind(StrEnum):
    OVERDUE = "overdue"
    DEPENDENCY_VIOLATED = "dependency_violated"
    BEHIND_BASELINE = "behind_baseline"
    FINISH_BEHIND_BASELINE = "finish_behind_baseline"


class ScheduleWarning(Schema):
    kind: WarningKind
    task_id: uuid.UUID | None
    key: str | None
    message: str
    days: int
