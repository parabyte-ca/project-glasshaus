import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    USER = "user"
    CHECKBOX = "checkbox"
    URL = "url"


class CustomField(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A typed field defined per project. Values live in ``tasks.custom_fields`` keyed by field id."""

    __tablename__ = "custom_fields"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    type: Mapped[FieldType] = mapped_column(
        Enum(FieldType, name="field_type", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Select options: [{"id": "...", "label": "...", "color": "#rrggbb"}]
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)
