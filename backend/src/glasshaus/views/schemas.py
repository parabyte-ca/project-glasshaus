import uuid
from datetime import date, datetime

from pydantic import Field

from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory
from glasshaus.tasks.models import Priority
from glasshaus.tasks.schemas import TaskSort
from glasshaus.views.models import ViewKind

GROUP_PATTERN = r"^(status|assignee|priority|cf:[0-9a-fA-F-]{36})$"
COLUMN_PATTERN = (
    r"^(key|title|status|priority|assignee|start_date|due_date|tags|estimate|updated_at|cf:[0-9a-fA-F-]{36})$"
)


class ViewFilters(Schema):
    status_ids: list[uuid.UUID] | None = None
    status_categories: list[StatusCategory] | None = None
    assignee_ids: list[uuid.UUID] | None = None
    unassigned: bool | None = None
    priorities: list[Priority] | None = None
    tags: list[str] | None = None
    q: str | None = Field(None, max_length=200)
    due_before: date | None = None
    due_after: date | None = None
    cf: list[str] | None = None
    top_level_only: bool = False


class ViewConfig(Schema):
    filters: ViewFilters = Field(default_factory=ViewFilters)
    group_by: str | None = Field(None, pattern=GROUP_PATTERN)
    sort: TaskSort = TaskSort.POSITION
    descending: bool = False
    sort_field: uuid.UUID | None = None
    columns: list[str] = Field(
        default_factory=lambda: ["key", "title", "status", "priority", "assignee", "due_date"], max_length=50
    )

    def model_post_init(self, _: object) -> None:
        import re

        bad = [c for c in self.columns if not re.match(COLUMN_PATTERN, c)]
        if bad:
            raise ValueError(f"unknown columns: {', '.join(bad)}")


class ViewRead(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: uuid.UUID | None
    name: str
    kind: ViewKind
    shared: bool
    config: ViewConfig
    position: float
    created_at: datetime
    updated_at: datetime


class ViewCreate(Schema):
    name: str = Field(min_length=1, max_length=100)
    kind: ViewKind
    shared: bool = False
    config: ViewConfig = Field(default_factory=ViewConfig)
    position: float | None = None


class ViewUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    kind: ViewKind | None = None
    shared: bool | None = None
    config: ViewConfig | None = None
    position: float | None = None
