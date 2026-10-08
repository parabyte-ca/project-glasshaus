import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.automation.schemas import RunStatus
from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow


class AutomationRule(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "automation_rules"
    __table_args__ = (Index("ix_automation_rules_project_enabled", "project_id", "enabled"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    run_on_automation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    webhook_secret: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AutomationRun(UUIDPk, TenantScoped, Base):
    """Execution log entry. ``dedupe_key`` makes event redelivery and time-based triggers run once."""

    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("rule_id", "dedupe_key"),
        Index("ix_automation_runs_project_started", "project_id", "started_at"),
        Index("ix_automation_runs_task_started", "task_id", "started_at"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="automation_run_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Inputs needed to retry: the triggering event (if any).
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecurringTask(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "recurring_tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    template: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))


class ProjectTemplate(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "project_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
