import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class Priority(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


PRIORITY_RANK = {Priority.NONE: 0, Priority.LOW: 1, Priority.MEDIUM: 2, Priority.HIGH: 3, Priority.URGENT: 4}


class Task(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "number"),
        Index("ix_tasks_project_position", "project_id", "position"),
        Index("ix_tasks_assignee_open", "assignee_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_tasks_tags", "tags", postgresql_using="gin"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_statuses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="task_priority", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Priority.NONE,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=list, server_default="{}"
    )
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config
