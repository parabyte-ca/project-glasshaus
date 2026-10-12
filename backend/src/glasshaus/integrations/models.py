import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow


class Integration(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A connection to another system. Outbound kinds (slack, teams, webhook) receive domain events;
    inbound kinds (github, gitlab, email) create links, comments or tasks in a project."""

    __tablename__ = "integrations"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    events: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list, server_default="{}"
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Webhook URL, signing secret or mailbox password, encrypted (core.crypto).
    secret: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationDelivery(UUIDPk, TenantScoped, Base):
    """One outbound message, retried with backoff until it succeeds or gives up."""

    __tablename__ = "integration_deliveries"
    __table_args__ = (
        UniqueConstraint("integration_id", "event_id"),
        Index(
            "ix_integration_deliveries_due", "next_attempt_at", postgresql_where=text("status = 'pending'")
        ),
        Index("ix_integration_deliveries_integration", "integration_id", "created_at"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending"
    )  # pending|success|failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarFeed(UUIDPk, TenantScoped, Base):
    """A personal iCalendar feed URL (secret token, hashed). Not under RLS: looked up by hash."""

    __tablename__ = "calendar_feeds"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChannelPost(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A scheduled post to a Slack or Teams channel: a saved report or a project's status.

    It runs with the access of the person who set it up (an integration manager), and a channel
    that belongs to one project only ever gets that project's numbers.
    """

    __tablename__ = "channel_posts"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # report | status
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_reports.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
