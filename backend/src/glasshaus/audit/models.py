import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, FetchedValue, Index, Integer, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, UUIDPk, utcnow


class AuditEntry(UUIDPk, TenantScoped, Base):
    """Append-only record of privileged or machine actions and every domain event.

    Postgres enforces the append-only part (migration 0.22): a trigger numbers each organization's
    entries (``seq``, no gaps), stamps ``created_at`` and chains ``hash`` = sha256(previous hash +
    this entry), and only the table owner may change or delete rows. The application role can only
    insert, and purge old entries through ``glasshaus_audit_purge`` (which records the purge).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_tenant_time", "tenant_id", "created_at"),
        Index("ux_audit_log_tenant_seq", "tenant_id", "seq", unique=True),
    )

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
    # Set by the database trigger; never written by the application.
    seq: Mapped[int] = mapped_column(BigInteger, FetchedValue(), nullable=False)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, FetchedValue())
    hash: Mapped[bytes] = mapped_column(LargeBinary, FetchedValue(), nullable=False)
