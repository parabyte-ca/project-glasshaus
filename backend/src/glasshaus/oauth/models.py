"""OAuth 2.1 storage for MCP clients. Secrets and tokens are stored as SHA-256 hashes only.

Not under row-level security: clients register and tokens are looked up before a tenant is known
(like API tokens); every row that carries data access is bound to a tenant and user.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, utcnow


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Plain: the MCP SDK compares it directly. DCR clients are mostly public ("none") anyway.
    client_secret: Mapped[str | None] = mapped_column(String(128))
    client_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )


class OAuthRequest(Base):
    """An /authorize request waiting for the user's consent in the web app."""

    __tablename__ = "oauth_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthGrant(Base):
    """Authorization codes, access tokens and refresh tokens (``kind``), bound to a user and tenant."""

    __tablename__ = "oauth_grants"
    __table_args__ = (Index("ix_oauth_grants_user", "user_id"), Index("ix_oauth_grants_family", "family_id"))

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # code | access | refresh
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # one consent; revoked together
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(500))
    # Authorization codes only: PKCE challenge and redirect binding.
    code_challenge: Mapped[str | None] = mapped_column(String(128))
    redirect_uri: Mapped[str | None] = mapped_column(String(2000))
    redirect_uri_explicit: Mapped[bool | None] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
