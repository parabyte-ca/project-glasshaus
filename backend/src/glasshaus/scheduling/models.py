import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class DependencyType(StrEnum):
    FINISH_TO_START = "fs"
    START_TO_START = "ss"
    FINISH_TO_FINISH = "ff"
    START_TO_FINISH = "sf"


class TaskDependency(UUIDPk, TenantScoped, TimestampMixin, Base):
    """``successor`` depends on ``predecessor``. ``lag_days`` > 0 adds a gap, < 0 is a lead."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("predecessor_id", "successor_id"),
        CheckConstraint("predecessor_id <> successor_id", name="not_self"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    predecessor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    successor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType, name="dependency_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DependencyType.FINISH_TO_START,
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Baseline(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A named snapshot of a project's planned dates."""

    __tablename__ = "baselines"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class BaselineTask(TenantScoped, Base):
    __tablename__ = "baseline_tasks"

    baseline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("baselines.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
