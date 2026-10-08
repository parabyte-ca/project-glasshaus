import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, UUIDPk, utcnow


class DomainEventRecord(UUIDPk, TenantScoped, Base):
    """Transactional outbox: written in the same transaction as the change, relayed to Redis afterwards."""

    __tablename__ = "domain_events"
    __table_args__ = (
        Index("ix_domain_events_unpublished", "occurred_at", postgresql_where=text("published_at IS NULL")),
        Index("ix_domain_events_aggregate", "aggregate_type", "aggregate_id", "occurred_at"),
        Index("ix_domain_events_project", "project_id", "occurred_at"),
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Project the event belongs to (if any): drives project activity feeds and realtime visibility.
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_method: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_client: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
