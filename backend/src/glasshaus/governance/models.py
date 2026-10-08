import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TimestampMixin


class OrgSettings(TimestampMixin, Base):
    """Per-organization governance settings (one row per tenant; created on first read)."""

    __tablename__ = "org_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    # Retention in days; 0 keeps forever.
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365"
    )
    activity_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    notification_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default="90"
    )
    deleted_task_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
