import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class SavedReport(UUIDPk, TenantScoped, TimestampMixin, Base):
    """A report definition. It holds no data: every run uses the viewer's own access."""

    __tablename__ = "saved_reports"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ReportSubscription(UUIDPk, TenantScoped, TimestampMixin, Base):
    """Email a saved report to one person on a schedule. Each send runs with that person's access."""

    __tablename__ = "report_subscriptions"
    __table_args__ = (UniqueConstraint("report_id", "user_id"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attach_csv: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class ReportAlert(UUIDPk, TenantScoped, TimestampMixin, Base):
    """Tell one person when a report's total crosses a threshold. Checked with that person's access."""

    __tablename__ = "report_alerts"
    __table_args__ = (UniqueConstraint("report_id", "user_id"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    measure: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # above | below
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    state: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown", server_default="unknown"
    )
    last_value: Mapped[float | None] = mapped_column(Float)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
