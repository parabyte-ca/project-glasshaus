import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TimestampMixin


class DirectorySync(TimestampMixin, Base):
    """Microsoft Graph directory sync for one organization (managers, job titles, departments)."""

    __tablename__ = "directory_syncs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Entra ID directory (tenant) id or primary domain, and an app registration with User.Read.All.
    directory_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    client_secret: Mapped[str | None] = mapped_column(String(1000))  # encrypted (core.crypto)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
