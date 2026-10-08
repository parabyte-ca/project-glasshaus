import uuid
from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from glasshaus.core.schemas import Schema
from glasshaus.fields.models import FieldType

COLOR = r"^#[0-9a-fA-F]{6}$"


class SelectOption(Schema):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8], pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=60)
    color: str = Field("#64748b", pattern=COLOR)


class FieldRead(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    type: FieldType
    description: str
    required: bool
    options: list[SelectOption]
    position: float
    created_at: datetime


def _check_options(type_: FieldType | None, options: list[SelectOption] | None) -> None:
    if options is None:
        return
    if options and type_ not in (FieldType.SELECT, FieldType.MULTI_SELECT, None):
        raise ValueError("options only apply to select and multi_select fields")
    ids = [o.id for o in options]
    labels = [o.label.lower() for o in options]
    if len(set(ids)) != len(ids) or len(set(labels)) != len(labels):
        raise ValueError("option ids and labels must be unique")
    if len(options) > 200:
        raise ValueError("at most 200 options")


class FieldCreate(Schema):
    name: str = Field(min_length=1, max_length=60)
    type: FieldType
    description: str = Field("", max_length=500)
    required: bool = False
    options: list[SelectOption] = Field(default_factory=list)
    position: float | None = None

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _check_options(self.type, self.options)
        if self.type in (FieldType.SELECT, FieldType.MULTI_SELECT) and not self.options:
            raise ValueError("select fields need at least one option")
        return self


class FieldUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, max_length=500)
    required: bool | None = None
    options: list[SelectOption] | None = Field(
        None, description="Full replacement list; values using removed options are cleared from tasks."
    )
    position: float | None = None

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _check_options(None, self.options)
        return self
