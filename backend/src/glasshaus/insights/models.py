import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class Dashboard(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "dashboards"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
