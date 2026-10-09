import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow


class ProjectAssistant(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A project's assistant settings. It reads the project as the organization's AI account."""

    __tablename__ = "project_assistants"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    configured_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    digest_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=8)
    digest_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    weekdays_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weekly_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weekly_weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)  # Friday
    weekly_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=14)
    stale_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Phase 2: put follow-ups, date changes and reassignments in the approval queue.
    suggest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    notify_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("integrations.id", ondelete="SET NULL"))
    next_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_weekly_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class ProjectBrief(UUIDPk, TenantScoped, Base):
    """One digest or weekly status draft written by the assistant. Titles inside are user content."""

    __tablename__ = "project_briefs"
    __table_args__ = (Index("ix_project_briefs_project_created", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # digest | weekly
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )


class AssistantSuggestion(UUIDPk, TenantScoped, Base):
    """A change the assistant proposes. Nothing happens until someone who could make the change
    approves it; the change is then made by the assistant account, naming who approved it."""

    __tablename__ = "assistant_suggestions"
    __table_args__ = (
        Index("ix_assistant_suggestions_project_status", "project_id", "status", "created_at"),
        Index(
            "uq_assistant_suggestions_open",
            "project_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status = 'open' AND dedupe_key IS NOT NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # comment | due_date | assign | task
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # rules | ai | notes
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open", server_default="open")
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    # The proposal and what it assumed (the task's due date or owner when it was made).
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(200))
