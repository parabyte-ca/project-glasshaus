"""The service context: who is acting, in which tenant, inside which transaction."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.core.rbac import ORG_ADMIN_ROLES, OrgRole

AuthMethod = Literal["session", "token", "system"]


@dataclass(frozen=True, slots=True)
class Actor:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    org_role: OrgRole
    method: AuthMethod
    scopes: frozenset[str] | None = None  # None = unrestricted (session/system)
    client: str | None = None  # API token id, MCP client id, ...

    @classmethod
    def system(cls, tenant_id: uuid.UUID) -> "Actor":
        return cls(tenant_id=tenant_id, user_id=None, org_role=OrgRole.OWNER, method="system")

    @property
    def is_org_admin(self) -> bool:
        return self.org_role in ORG_ADMIN_ROLES


@dataclass(slots=True)
class ServiceContext:
    session: AsyncSession
    actor: Actor
    # Per-transaction memo (e.g. resolved project roles); never shared across requests.
    cache: dict[Any, Any] = field(default_factory=dict)
    pending_events: list[uuid.UUID] = field(default_factory=list)

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.actor.tenant_id
