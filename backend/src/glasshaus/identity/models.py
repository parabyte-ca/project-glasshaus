import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow
from glasshaus.core.rbac import OrgRole, WorkspaceRole


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], validate_strings=True)


class User(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_tenant_email", "tenant_id", text("lower(email)"), unique=True),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    org_role: Mapped[OrgRole] = mapped_column(
        _enum(OrgRole, "org_role"), nullable=False, default=OrgRole.MEMBER
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Identifier the provisioning system (SCIM) uses for this user.
    external_id: Mapped[str | None] = mapped_column(String(255))
    # Workload capacity: minutes available per working day, and which weekdays (0 = Monday) are worked.
    capacity_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=480, server_default="480")
    working_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, default=lambda: [0, 1, 2, 3, 4], server_default="{0,1,2,3,4}"
    )
    # "person", or "assistant" for the organization's AI project assistant: it cannot sign in, is
    # not listed or provisioned as a person and is never assigned work (glasshaus.assistant).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="person", server_default="person")
    # Reporting line (glasshaus.people): who this person reports to, and where that came from:
    # "scim" (the identity provider pushes it) or "graph" (the nightly Microsoft Graph sync).
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manager_source: Mapped[str | None] = mapped_column(String(10))
    job_title: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    # First-run guidance this person has seen or dismissed (product tour, checklist, tips).
    onboarding: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Workspace(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="", server_default="")


class WorkspaceMember(TenantScoped, TimestampMixin, Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(_enum(WorkspaceRole, "workspace_role"), nullable=False)


class ApiToken(UUIDPk, TenantScoped, TimestampMixin, Base):
    """Personal access token. Only a SHA-256 of the secret is stored. Not under RLS: it is looked up by
    hash before the tenant is known, and every query also filters by tenant_id."""

    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPk, TenantScoped, Base):
    """Browser refresh session (rotating refresh token, hashed). Not under RLS (looked up by hash)."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="", server_default="")
    ip: Mapped[str] = mapped_column(String(64), default="", server_default="")


ASSISTANT_KIND = "assistant"


RESERVED_DOMAIN = "glasshaus.invalid"  # the assistant's address; no person may take it


def reserved_email(email: str) -> bool:
    return email.strip().lower().endswith("@" + RESERVED_DOMAIN)


def is_assistant(user: User | None) -> bool:
    return user is not None and user.kind == ASSISTANT_KIND
