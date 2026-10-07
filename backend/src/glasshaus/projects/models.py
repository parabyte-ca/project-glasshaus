import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk
from glasshaus.core.rbac import ProjectRole


class StatusCategory(StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], validate_strings=True)


class Project(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(10000), nullable=False, default="", server_default="")
    task_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProjectMember(TenantScoped, TimestampMixin, Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(_enum(ProjectRole, "project_role"), nullable=False)


class ProjectStatus(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "project_statuses"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[StatusCategory] = mapped_column(_enum(StatusCategory, "status_category"), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748b", server_default="#64748b")
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)


DEFAULT_STATUSES: tuple[tuple[str, StatusCategory, str], ...] = (
    ("Backlog", StatusCategory.BACKLOG, "#94a3b8"),
    ("To do", StatusCategory.TODO, "#64748b"),
    ("In progress", StatusCategory.IN_PROGRESS, "#0284c7"),
    ("Done", StatusCategory.DONE, "#16a34a"),
    ("Cancelled", StatusCategory.CANCELLED, "#dc2626"),
)
