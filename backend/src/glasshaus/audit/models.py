import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, UUIDPk, utcnow


class AuditEntry(UUIDPk, TenantScoped, Base):
    """Append-only record of privileged or machine actions (MCP tool calls in 0.7; more in 0.8)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tenant_time", "tenant_id", "created_at"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column()  # no FK: entries outlive deleted users
    actor_method: Mapped[str] = mapped_column(String(20), nullable=False)
    client: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | denied | error | rate_limited
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()"), nullable=False
    )
