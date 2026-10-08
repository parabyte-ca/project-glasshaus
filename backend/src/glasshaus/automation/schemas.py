"""Automation rule language: trigger -> conditions -> actions. Stored as JSON on the rule."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Self
from zoneinfo import available_timezones

from pydantic import Field, field_validator, model_validator

from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory
from glasshaus.projects.schemas import KEY_PATTERN
from glasshaus.tasks.models import Priority


class TriggerType(StrEnum):
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    STATUS_CHANGED = "status_changed"
    COMMENT_CREATED = "comment_created"
    DUE_SOON = "due_soon"
    SCHEDULED = "scheduled"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduleSpec(Schema):
    frequency: Frequency
    hour: int = Field(9, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    weekday: int | None = Field(None, ge=0, le=6, description="0 = Monday (weekly only).")
    day: int | None = Field(None, ge=1, le=28, description="Day of month (monthly only).")
    timezone: str = Field("UTC", description="IANA time zone, e.g. America/Toronto.")

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v != "UTC" and v not in available_timezones():
            raise ValueError("unknown time zone")
        return v

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.frequency == Frequency.WEEKLY and self.weekday is None:
            raise ValueError("weekly schedules need a weekday")
        if self.frequency == Frequency.MONTHLY and self.day is None:
            raise ValueError("monthly schedules need a day")
        return self


class Trigger(Schema):
    type: TriggerType
    field: (
        Literal["status_id", "priority", "assignee_id", "due_date", "start_date", "title", "tags"] | None
    ) = Field(None, description="task_updated only: fire when this field changed (any field when omitted).")
    to_category: StatusCategory | None = Field(None, description="status_changed only: new status category.")
    to_status_id: uuid.UUID | None = Field(None, description="status_changed only: new status.")
    days_before: int | None = Field(
        None, ge=0, le=365, description="due_soon only: days before the due date."
    )
    schedule: ScheduleSpec | None = Field(None, description="scheduled only.")

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.type == TriggerType.DUE_SOON and self.days_before is None:
            raise ValueError("due_soon triggers need days_before")
        if self.type == TriggerType.SCHEDULED and self.schedule is None:
            raise ValueError("scheduled triggers need a schedule")
        return self


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    LT = "lt"
    GT = "gt"
    IS_EMPTY = "is_empty"
    NOT_EMPTY = "not_empty"


CONDITION_FIELD = (
    r"^(status_id|status_category|priority|assignee_id|tags|title|due_in_days|is_subtask"
    r"|cf:[0-9a-fA-F-]{36})$"
)


class Condition(Schema):
    field: str = Field(pattern=CONDITION_FIELD)
    op: Operator
    value: Any = None


class ActionType(StrEnum):
    SET_STATUS = "set_status"
    SET_PRIORITY = "set_priority"
    ASSIGN = "assign"
    UNASSIGN = "unassign"
    SET_DUE_DATE = "set_due_date"
    ADD_TAGS = "add_tags"
    REMOVE_TAGS = "remove_tags"
    SET_CUSTOM_FIELD = "set_custom_field"
    CREATE_SUBTASK = "create_subtask"
    POST_COMMENT = "post_comment"
    NOTIFY = "notify"
    WEBHOOK = "webhook"


class Action(Schema):
    """One step. Text fields accept placeholders: {{task.key}}, {{task.title}}, {{task.status}},
    {{task.priority}}, {{task.due_date}}, {{task.url}}, {{project.name}}, {{rule.name}}."""

    type: ActionType
    status_id: uuid.UUID | None = None
    status_category: StatusCategory | None = None
    priority: Priority | None = None
    user: str | None = Field(None, description="User id, or 'reporter' / 'actor' (assign).")
    users: list[str] | None = Field(None, description="notify: user ids and/or 'assignee', 'reporter'.")
    days_from_now: int | None = Field(None, ge=-365, le=3650, description="set_due_date: relative to today.")
    tags: list[str] | None = None
    field_id: uuid.UUID | None = None
    value: Any = None
    title: str | None = Field(None, max_length=500)
    body: str | None = Field(None, max_length=20_000)
    url: str | None = Field(None, max_length=2000, pattern=r"^https?://")

    @model_validator(mode="after")
    def _shape(self) -> Self:
        need: dict[ActionType, tuple[str, ...]] = {
            ActionType.SET_PRIORITY: ("priority",),
            ActionType.ASSIGN: ("user",),
            ActionType.SET_DUE_DATE: ("days_from_now",),
            ActionType.ADD_TAGS: ("tags",),
            ActionType.REMOVE_TAGS: ("tags",),
            ActionType.SET_CUSTOM_FIELD: ("field_id",),
            ActionType.CREATE_SUBTASK: ("title",),
            ActionType.POST_COMMENT: ("body",),
            ActionType.NOTIFY: ("users", "title"),
            ActionType.WEBHOOK: ("url",),
        }
        missing = [f for f in need.get(self.type, ()) if getattr(self, f) is None]
        if self.type == ActionType.SET_STATUS and self.status_id is None and self.status_category is None:
            missing.append("status_id or status_category")
        if missing:
            raise ValueError(f"{self.type.value} needs {', '.join(missing)}")
        return self


class RuleBase(Schema):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    trigger: Trigger
    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    actions: list[Action] = Field(min_length=1, max_length=20)
    run_on_automation: bool = Field(
        False, description="Also react to changes made by automations (off prevents loops)."
    )


class RuleCreate(RuleBase):
    pass


class RuleUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    enabled: bool | None = None
    trigger: Trigger | None = None
    conditions: list[Condition] | None = Field(None, max_length=20)
    actions: list[Action] | None = Field(None, min_length=1, max_length=20)
    run_on_automation: bool | None = None


class RuleRead(RuleBase):
    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID | None
    webhook_secret: str | None = Field(
        description="HMAC-SHA256 key for X-Glasshaus-Signature (project admins only)."
    )
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime


class RunStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunRead(Schema):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str
    task_id: uuid.UUID | None
    trigger_type: str
    status: RunStatus
    error: str | None
    results: dict[str, Any]
    attempts: int
    started_at: datetime
    finished_at: datetime | None


class RuleTestResult(Schema):
    matched: bool
    conditions: list[dict[str, Any]] = Field(description="Each condition with its outcome.")
    planned_actions: list[str]


class RuleTestRequest(Schema):
    rule: RuleBase
    task: str = Field(description="Task id or reference (e.g. WEB-12) to evaluate the conditions against.")


# --------------------------------------------------------------------------- recurring tasks


class RecurringTemplate(Schema):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field("", max_length=100_000)
    priority: Priority = Priority.NONE
    assignee_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    estimate_minutes: int | None = Field(None, ge=0, le=1_000_000)
    due_in_days: int | None = Field(None, ge=0, le=365, description="Due date relative to the creation day.")
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class RecurringCreate(Schema):
    enabled: bool = True
    template: RecurringTemplate
    schedule: ScheduleSpec


class RecurringUpdate(Schema):
    enabled: bool | None = None
    template: RecurringTemplate | None = None
    schedule: ScheduleSpec | None = None


class RecurringRead(RecurringCreate):
    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID | None
    next_run_at: datetime
    last_run_at: datetime | None
    last_task_id: uuid.UUID | None
    created_at: datetime


# --------------------------------------------------------------------------- project templates


class TemplateCreate(Schema):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=2000)
    include_tasks: bool = True
    include_automations: bool = Field(True, description="Automation rules and recurring tasks.")


class TemplateSummary(Schema):
    statuses: int
    fields: int
    views: int
    tasks: int
    dependencies: int
    rules: int
    recurring: int


class TemplateRead(Schema):
    id: uuid.UUID
    name: str
    description: str
    created_by: uuid.UUID | None
    created_at: datetime
    summary: TemplateSummary


class TemplateInstantiate(Schema):
    workspace_id: uuid.UUID
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=10000, description="Defaults to the template's.")
    start_date: date | None = Field(
        None, description="Task dates shift so the earliest lands here (default today)."
    )
