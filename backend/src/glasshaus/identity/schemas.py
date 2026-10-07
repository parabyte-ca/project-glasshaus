import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from glasshaus.core.rbac import OrgRole, Scope, WorkspaceRole
from glasshaus.core.schemas import Schema

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"


class LoginRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    organization: str | None = Field(None, description="Organization slug; defaults to the default tenant.")


class UserRead(Schema):
    id: uuid.UUID
    email: str
    name: str
    org_role: OrgRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(Schema):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(None, min_length=12, max_length=1024)
    org_role: OrgRole = OrgRole.MEMBER


class UserUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    org_role: OrgRole | None = None
    is_active: bool | None = None


class PasswordChange(Schema):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class WorkspaceRead(Schema):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    created_at: datetime


class WorkspaceCreate(Schema):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    description: str = Field("", max_length=2000)


class WorkspaceUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class WorkspaceMemberRead(Schema):
    user_id: uuid.UUID
    role: WorkspaceRole


class WorkspaceMemberSet(Schema):
    user_id: uuid.UUID
    role: WorkspaceRole


class ApiTokenCreate(Schema):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(min_length=1)
    expires_in_days: int | None = Field(90, ge=1, le=3650, description="null for a non-expiring token")

    @field_validator("scopes")
    @classmethod
    def _dedupe(cls, v: list[Scope]) -> list[Scope]:
        return sorted(set(v))


class ApiTokenRead(Schema):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    token: str = Field(description="The secret. Shown once; store it securely.")
