import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class ViewKind(StrEnum):
    LIST = "list"
    BOARD = "board"
    TABLE = "table"
    TIMELINE = "timeline"
    CALENDAR = "calendar"


class SavedView(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "saved_views"
    __table_args__ = (Index("ix_saved_views_project", "project_id", "position"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[ViewKind] = mapped_column(
        Enum(ViewKind, name="view_kind", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)
