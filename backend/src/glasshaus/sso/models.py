import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow


class IdentityProvider(UUIDPk, TenantScoped, TimestampMixin, Base):
    """An OIDC or SAML identity provider for single sign-on."""

    __tablename__ = "identity_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # oidc | saml
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # OIDC client secret, encrypted (core.crypto).
    client_secret: Mapped[str | None] = mapped_column(String(1000))
    allowed_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(253)), nullable=False, default=list, server_default="{}"
    )
    jit_provisioning: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    default_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member"
    )
    # When on, members and admins must use SSO; owners keep password sign-in as break-glass access.
    enforce: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class UserIdentity(UUIDPk, TenantScoped, Base):
    """Links a user to their subject at an identity provider."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity_providers.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
