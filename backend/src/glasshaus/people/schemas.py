import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from glasshaus.core.schemas import Schema

Visibility = Literal["all", "shared"]


class TeamProject(Schema):
    id: uuid.UUID
    key: str | None = Field(description="Empty when you cannot open the project (visibility 'shared').")
    name: str | None = Field(description="Empty when you cannot open the project (visibility 'shared').")
    health: str = Field(description="on_track, at_risk or off_track (from the project's overdue work).")
    open_tasks: int = Field(description="This person's open tasks in the project.")
    visible: bool = Field(description="You can open this project yourself.")


class TeamTask(Schema):
    id: uuid.UUID
    key: str
    title: str
    project_key: str
    project_name: str
    status: str
    category: str
    priority: str
    due_date: date | None
    updated_at: datetime
    completed_at: datetime | None


class TeamMember(Schema):
    id: uuid.UUID
    name: str
    email: str
    job_title: str | None
    department: str | None
    manager_id: uuid.UUID | None
    level: int = Field(description="1 for a direct report, 2 for their reports, and so on.")
    # Workload
    open: int
    in_progress: int
    overdue: int
    due_this_week: int
    # Time logged (minutes) and what the person has available in a week
    logged_this_week: int
    logged_last_week: int
    capacity_week: int
    # Recent activity
    completed_last_7_days: int
    stale: int = Field(description="In-progress tasks without an update for 5 days or more.")
    recent: list[TeamTask] = Field(description="Up to 3 tasks finished in the last 7 days.")
    projects: list[TeamProject]


class TeamRead(Schema):
    visibility: Visibility = Field(
        description="'all': your reports' work in every project; 'shared': only projects you can open."
    )
    direct_reports: int
    people: list[TeamMember]


class TeamTasks(Schema):
    person: uuid.UUID
    hidden: int = Field(0, description="Tasks in projects you cannot open (visibility 'shared').")
    tasks: list[TeamTask]


class DirectorySyncRead(Schema):
    enabled: bool
    directory_id: str
    client_id: str
    client_secret: str | None = Field(description="Whether a secret is stored (never its value).")
    last_run_at: datetime | None
    last_error: str | None
    last_result: dict[str, int]


class DirectorySyncWrite(Schema):
    enabled: bool = False
    directory_id: str = Field(
        "", max_length=100, description="Directory (tenant) ID or primary domain in Microsoft Entra ID."
    )
    client_id: str = Field("", max_length=100, description="Application (client) ID of the app registration.")
    client_secret: str | None = Field(
        None, max_length=500, description="Leave out to keep the stored secret; empty string removes it."
    )

    @field_validator("directory_id", "client_id")
    @classmethod
    def _plain(cls, v: str) -> str:
        import re

        v = v.strip()
        if v and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", v):
            raise ValueError("use the ID (a GUID) or domain exactly as Entra ID shows it")
        return v
