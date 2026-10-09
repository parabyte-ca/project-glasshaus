"""Declarative base and shared mixins.

Every tenant-owned table inherits ``TenantScoped`` (a ``tenant_id`` column). Tables listed in
``RLS_TABLES`` get a Postgres row-level-security policy keyed on the ``app.tenant_id`` setting
(see ``glasshaus.db``), so a query can never see another tenant's rows even if a filter is missed.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    # Python-side defaults keep values loaded after flush (no expired attributes / async lazy loads);
    # server defaults cover rows written outside the ORM.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class TenantScoped:
    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - SQLAlchemy declared_attr signature
        return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


# Tables protected by row-level security (kept in sync with migrations by a test).
RLS_TABLES = (
    "users",
    "workspaces",
    "workspace_members",
    "projects",
    "project_members",
    "project_statuses",
    "tasks",
    "domain_events",
    "custom_fields",
    "comments",
    "notifications",
    "saved_views",
    "task_dependencies",
    "baselines",
    "baseline_tasks",
    "automation_rules",
    "automation_runs",
    "recurring_tasks",
    "project_templates",
    "time_entries",
    "running_timers",
    "dashboards",
    "saved_reports",
    "report_subscriptions",
    "report_alerts",
    "channel_posts",
    "push_subscriptions",
    "portfolios",
    "portfolio_projects",
    "objectives",
    "key_results",
    "kr_check_ins",
    "audit_log",
    "org_settings",
    "identity_providers",
    "user_identities",
    "integrations",
    "integration_deliveries",
)
