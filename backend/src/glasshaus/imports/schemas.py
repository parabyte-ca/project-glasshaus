import uuid
from typing import Literal

from pydantic import Field

from glasshaus.core.schemas import Schema
from glasshaus.tasks.models import Priority

MAX_ROWS = 5000

# Glasshaus fields a column can be mapped to; custom fields are "cf:<field id>".
ImportField = Literal[
    "external_id",
    "title",
    "description",
    "status",
    "priority",
    "assignee",
    "start_date",
    "due_date",
    "estimate",
    "tags",
    "parent",
    "comments",
    "links",
]


class ImportRow(Schema):
    """One spreadsheet row, already mapped to Glasshaus fields. Values are the cells' text."""

    row: int = Field(ge=1, description="Row number in the file, used in messages.")
    external_id: str | None = Field(None, max_length=200, description="The source's own id for this item.")
    title: str | None = Field(None, max_length=2000)
    description: str | None = Field(None, max_length=100_000)
    status: str | None = Field(None, max_length=200)
    priority: str | None = Field(None, max_length=50)
    assignee: str | None = Field(None, max_length=320, description="Email address (or exact name).")
    start_date: str | None = Field(None, max_length=40)
    due_date: str | None = Field(None, max_length=40)
    estimate: str | None = Field(None, max_length=40, description="Hours, or e.g. '1h 30m'.")
    tags: str | None = Field(None, max_length=2000, description="Separated by commas or semicolons.")
    parent: str | None = Field(None, max_length=200, description="The parent item's external id.")
    comments: list[str] = Field(default_factory=list, max_length=50)
    links: list[str] = Field(default_factory=list, max_length=20)
    custom_fields: dict[str, str] = Field(default_factory=dict, description="Field id -> cell text.")


class ImportRequest(Schema):
    source: str = Field(
        "spreadsheet",
        pattern=r"^[a-z0-9_-]{1,32}$",
        description="Where the rows came from (spreadsheet, nimble, ...). Re-imports match within a source.",
    )
    file_name: str | None = Field(None, max_length=255)
    fields: list[str] = Field(
        description="The fields the file has columns for. On re-import only these change.", max_length=100
    )
    date_format: Literal["auto", "ymd", "dmy", "mdy"] = "auto"
    status_map: dict[str, uuid.UUID] = Field(
        default_factory=dict, description="Lower-case status text -> this project's status id."
    )
    priority_map: dict[str, Priority] = Field(
        default_factory=dict, description="Lower-case text -> priority."
    )
    rows: list[ImportRow] = Field(min_length=1, max_length=MAX_ROWS)
    dry_run: bool = Field(False, description="Check everything and report, but change nothing.")


class ImportProblem(Schema):
    row: int
    message: str


class UnmatchedPerson(Schema):
    value: str = Field(description="The name or email in the file.")
    rows: int = Field(description="How many rows name them.")
    reason: str


class ImportResult(Schema):
    dry_run: bool
    created: int
    updated: int
    unchanged: int
    skipped: int
    comments_added: int
    problems: list[ImportProblem]
    unmatched_people: list[UnmatchedPerson]
    warnings: list[str]
