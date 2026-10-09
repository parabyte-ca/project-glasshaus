import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, text
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
