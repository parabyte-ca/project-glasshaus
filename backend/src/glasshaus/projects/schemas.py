import uuid
from datetime import datetime

from pydantic import Field

from glasshaus.core.rbac import ProjectRole
from glasshaus.core.schemas import Schema
from glasshaus.projects.models import StatusCategory

KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,9}$"
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class StatusRead(Schema):
    id: uuid.UUID
    name: str
    category: StatusCategory
    color: str
    position: float


class StatusCreate(Schema):
    name: str = Field(min_length=1, max_length=60)
    category: StatusCategory
    color: str = Field("#64748b", pattern=COLOR_PATTERN)
    position: float | None = None


class StatusUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=60)
    category: StatusCategory | None = None
    color: str | None = Field(None, pattern=COLOR_PATTERN)
    position: float | None = None


class ProjectRead(Schema):
    id: uuid.UUID
    workspace_id: uuid.UUID
    key: str
    name: str
    description: str
    auto_schedule: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    my_role: ProjectRole | None = Field(None, description="The caller's effective role on this project.")


class ProjectDetail(ProjectRead):
    statuses: list[StatusRead]


class ProjectCreate(Schema):
    workspace_id: uuid.UUID
    key: str = Field(
        pattern=KEY_PATTERN, description="Short uppercase key used in task references, e.g. WEB-12."
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=10000)


class ProjectUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=10000)
    archived: bool | None = None
    auto_schedule: bool | None = Field(None, description="Move dependent tasks later automatically.")


class ProjectMemberRead(Schema):
    user_id: uuid.UUID
    role: ProjectRole


class ProjectMemberSet(Schema):
    user_id: uuid.UUID
    role: ProjectRole


class DeletePreview(Schema):
    """Returned by destructive operations when dry_run=true (and as the result when executed)."""

    resource: str
    id: uuid.UUID
    executed: bool
    affected: dict[str, int] = Field(description="Counts of dependent records that are removed as well.")
