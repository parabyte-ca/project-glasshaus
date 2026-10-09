"""SCIM 2.0 (RFC 7643/7644) provisioning: Users map to accounts, Groups map to workspaces.

Deleting or deactivating a user disables the account (history is kept). Group members become
workspace members with the "member" role; workspace admins are managed in Glasshaus.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.config import get_settings
from glasshaus.core import events
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, Unauthenticated
from glasshaus.core.rbac import OrgRole, Permission, WorkspaceRole
from glasshaus.core.schemas import Schema
from glasshaus.identity import security
from glasshaus.identity.models import ASSISTANT_KIND, User, Workspace, WorkspaceMember, is_assistant
from glasshaus.scim.models import ScimToken

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
TOKEN_PREFIX = "ghs_"  # noqa: S105 - a public prefix, not a secret
MAX_RESULTS = 200
FILTER = re.compile(
    r'^\s*(userName|externalId|displayName|emails\.value)\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE
)


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


# --------------------------------------------------------------------------- tokens (admin)


class ScimTokenRead(Schema):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ScimTokenCreated(ScimTokenRead):
    token: str
    base_url: str


class ScimTokenCreate(Schema):
    name: str


def base_url() -> str:
    return f"{get_settings().public_url.rstrip('/')}/scim/v2"


async def list_tokens(ctx: ServiceContext) -> list[ScimTokenRead]:
    require_org(ctx, Permission.ORG_MANAGE)
    rows = await ctx.session.scalars(
        select(ScimToken).where(ScimToken.tenant_id == ctx.tenant_id).order_by(ScimToken.created_at.desc())
    )
    return [ScimTokenRead.model_validate(t) for t in rows.all()]


async def create_token(ctx: ServiceContext, data: ScimTokenCreate) -> ScimTokenCreated:
    require_org(ctx, Permission.ORG_MANAGE)
    import secrets

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ScimToken(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=data.name[:100] or "SCIM",
        prefix=raw[:12],
        token_hash=security.sha256(raw),
        created_by=ctx.actor.user_id,
    )
    ctx.session.add(token)
    await ctx.session.flush()
    events.emit(ctx, "scim.token_created", "scim_token", token.id, {"name": token.name})
    return ScimTokenCreated(
        **ScimTokenRead.model_validate(token).model_dump(), token=raw, base_url=base_url()
    )


async def revoke_token(ctx: ServiceContext, token_id: uuid.UUID) -> None:
    require_org(ctx, Permission.ORG_MANAGE)
    token = await ctx.session.get(ScimToken, token_id)
    if token is None or token.tenant_id != ctx.tenant_id:
        raise NotFound("SCIM token not found")
    token.revoked_at = datetime.now(UTC)
    events.emit(ctx, "scim.token_revoked", "scim_token", token.id, {"name": token.name})


async def actor_from_scim_token(session: AsyncSession, raw: str) -> Actor:
    from glasshaus.db import apply_tenant

    if not raw.startswith(TOKEN_PREFIX):
        raise Unauthenticated("invalid SCIM token")
    token = await session.scalar(select(ScimToken).where(ScimToken.token_hash == security.sha256(raw)))
    if token is None or token.revoked_at is not None:
        raise Unauthenticated("invalid SCIM token")
    await apply_tenant(session, token.tenant_id)
    token.last_used_at = datetime.now(UTC)
    return Actor(
        tenant_id=token.tenant_id,
        user_id=None,
        org_role=OrgRole.ADMIN,
        method="scim",
        scopes=None,
        client=f"scim:{token.id}",
    )


# --------------------------------------------------------------------------- representation


def user_resource(user: User) -> dict[str, Any]:
    given, _, family = user.name.partition(" ")
    return {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "externalId": user.external_id,
        "userName": user.email,
        "displayName": user.name,
        "name": {"formatted": user.name, "givenName": given, "familyName": family},
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat(),
            "lastModified": user.updated_at.isoformat(),
            "location": f"{base_url()}/Users/{user.id}",
        },
    }


async def group_resource(session: AsyncSession, ws: Workspace) -> dict[str, Any]:
    members = (
        await session.execute(
            select(User.id, User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == ws.id)
            .order_by(User.email)
        )
    ).all()
    return {
        "schemas": [GROUP_SCHEMA],
        "id": str(ws.id),
        "displayName": ws.name,
        "members": [{"value": str(m.id), "display": m.email, "type": "User"} for m in members],
        "meta": {
            "resourceType": "Group",
            "created": ws.created_at.isoformat(),
            "lastModified": ws.updated_at.isoformat(),
            "location": f"{base_url()}/Groups/{ws.id}",
        },
    }


def list_response(resources: list[dict[str, Any]], total: int, start: int) -> dict[str, Any]:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _email_of(body: dict[str, Any]) -> str:
    emails = body.get("emails") or []
    primary = next((e for e in emails if isinstance(e, dict) and e.get("primary")), None) or (
        emails[0] if emails and isinstance(emails[0], dict) else None
    )
    email = (primary or {}).get("value") or body.get("userName")
    if not email or "@" not in str(email):
        raise ScimError(400, "userName or emails must hold an email address", "invalidValue")
    return str(email).strip()


def _name_of(body: dict[str, Any], fallback: str) -> str:
    name = body.get("displayName") or (body.get("name") or {}).get("formatted")
    if not name:
        n = body.get("name") or {}
        name = " ".join(p for p in (n.get("givenName"), n.get("familyName")) if p)
    return (name or fallback.split("@")[0])[:200]


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ScimError(404, "resource not found") from exc


# --------------------------------------------------------------------------- users


async def list_users(ctx: ServiceContext, filter_: str | None, start: int, count: int) -> dict[str, Any]:
    stmt = select(User).where(User.kind != ASSISTANT_KIND)  # the AI assistant is not provisioned
    if filter_:
        m = FILTER.match(filter_)
        if not m:
            raise ScimError(400, "only 'attribute eq \"value\"' filters are supported", "invalidFilter")
        attr, value = m.group(1).lower(), m.group(2)
        if attr in ("username", "emails.value"):
            stmt = stmt.where(func.lower(User.email) == value.lower())
        elif attr == "externalid":
            stmt = stmt.where(User.external_id == value)
        else:
            stmt = stmt.where(User.name == value)
    total = await ctx.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    start = max(start, 1)
    rows = await ctx.session.scalars(
        stmt.order_by(User.created_at, User.id).offset(start - 1).limit(min(max(count, 0), MAX_RESULTS))
    )
    return list_response([user_resource(u) for u in rows.all()], total, start)


async def get_user(ctx: ServiceContext, user_id: str) -> dict[str, Any]:
    user = await ctx.session.get(User, _uuid(user_id))
    if user is None or is_assistant(user):
        raise ScimError(404, "user not found")
    return user_resource(user)


async def create_user(ctx: ServiceContext, body: dict[str, Any]) -> dict[str, Any]:
    email = _email_of(body)
    exists = await ctx.session.scalar(select(User.id).where(func.lower(User.email) == email.lower()))
    if exists:
        raise ScimError(409, "a user with this userName already exists", "uniqueness")
    user = User(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        email=email,
        name=_name_of(body, email),
        org_role=OrgRole.MEMBER,
        is_active=bool(body.get("active", True)),
        external_id=(str(body["externalId"])[:255] if body.get("externalId") else None),
    )
    ctx.session.add(user)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise ScimError(409, "a user with this userName already exists", "uniqueness") from exc
    events.emit(ctx, "user.created", "user", user.id, {"email": user.email, "source": "scim"})
    return user_resource(user)


PROTECTED_ROLES = (OrgRole.OWNER, OrgRole.ADMIN)


def _guard(user: User, change: str) -> None:
    """SCIM manages ordinary accounts only. Owners and admins are changed in Glasshaus itself, so a
    leaked SCIM token or a compromised IdP cannot take them over (email change) or lock them out."""
    if user.org_role in PROTECTED_ROLES:
        raise ScimError(
            400,
            f"{user.org_role.value} accounts are managed in Glasshaus, not through SCIM ({change})",
            "mutability",
        )


async def _set_email(ctx: ServiceContext, user: User, email: str) -> None:
    if email.lower() == user.email.lower():
        if email != user.email:
            user.email = email  # case-only change
        return
    _guard(user, "email")
    if user.external_id is None:
        raise ScimError(
            400, "set externalId first: SCIM changes the email only of accounts it provisioned", "mutability"
        )
    clash = await ctx.session.scalar(
        select(User.id).where(func.lower(User.email) == email.lower(), User.id != user.id)
    )
    if clash:
        raise ScimError(409, "a user with this userName already exists", "uniqueness")
    user.email = email
    from glasshaus.governance.service import revoke_user_sessions

    await revoke_user_sessions(ctx, user.id)


def _set_external_id(user: User, value: str | None) -> None:
    if value != user.external_id:
        _guard(user, "externalId")
        user.external_id = value


async def _set_active(ctx: ServiceContext, user: User, active: bool) -> None:
    if user.is_active == active:
        return
    _guard(user, "active")
    if active and user.external_id is None:
        raise ScimError(400, "this account was deactivated in Glasshaus; reactivate it there", "mutability")
    user.is_active = active
    if not active:
        from glasshaus.governance.service import revoke_user_sessions

        await revoke_user_sessions(ctx, user.id)


async def replace_user(ctx: ServiceContext, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    user = await ctx.session.get(User, _uuid(user_id))
    if user is None or is_assistant(user):
        raise ScimError(404, "user not found")
    email = _email_of(body)
    if "externalId" in body:
        _set_external_id(user, str(body["externalId"])[:255] if body["externalId"] else None)
    await _set_email(ctx, user, email)
    user.name = _name_of(body, email)
    await _set_active(ctx, user, bool(body.get("active", True)))
    await ctx.session.flush()
    events.emit(ctx, "user.updated", "user", user.id, {"source": "scim", "active": user.is_active})
    return user_resource(user)


async def patch_user(ctx: ServiceContext, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    user = await ctx.session.get(User, _uuid(user_id))
    if user is None or is_assistant(user):
        raise ScimError(404, "user not found")
    for op in body.get("Operations") or []:
        kind = str(op.get("op", "")).lower()
        path = (op.get("path") or "").strip()
        value = op.get("value")
        if kind not in ("add", "replace", "remove"):
            raise ScimError(400, f"unsupported op {kind!r}", "invalidSyntax")
        updates: dict[str, Any] = value if not path and isinstance(value, dict) else {path: value}
        for key, val in updates.items():
            k = key.lower()
            if k == "active":
                active = val if isinstance(val, bool) else str(val).lower() == "true"
                await _set_active(ctx, user, kind != "remove" and active)
            elif k in ("displayname", "name.formatted"):
                user.name = str(val)[:200] if val else user.name
            elif k == "name" and isinstance(val, dict):
                user.name = _name_of({"name": val}, user.email)
            elif k == "externalid":
                _set_external_id(user, str(val)[:255] if val and kind != "remove" else None)
            elif k in ("username", 'emails[type eq "work"].value', "emails"):
                email = _email_of({"userName": val} if not isinstance(val, list) else {"emails": val})
                await _set_email(ctx, user, email)
            # Other attributes (title, phoneNumbers, …) are accepted and ignored.
    await ctx.session.flush()
    events.emit(ctx, "user.updated", "user", user.id, {"source": "scim", "active": user.is_active})
    return user_resource(user)


async def delete_user(ctx: ServiceContext, user_id: str) -> None:
    user = await ctx.session.get(User, _uuid(user_id))
    if user is None or is_assistant(user):
        raise ScimError(404, "user not found")
    await _set_active(ctx, user, False)
    events.emit(ctx, "user.updated", "user", user.id, {"source": "scim", "active": False})


# --------------------------------------------------------------------------- groups (workspaces)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:55] or "group"
    return slug


async def _set_members(ctx: ServiceContext, ws: Workspace, add: list[str], remove: list[str]) -> None:
    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert

    for raw in add:
        uid = _uuid(raw)
        if (member := await ctx.session.get(User, uid)) is None or is_assistant(member):
            raise ScimError(400, f"unknown member {raw}", "invalidValue")
        await ctx.session.execute(
            insert(WorkspaceMember)
            .values(tenant_id=ctx.tenant_id, workspace_id=ws.id, user_id=uid, role=WorkspaceRole.MEMBER)
            .on_conflict_do_nothing()
        )
    if remove:
        await ctx.session.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id.in_([_uuid(r) for r in remove]),
            )
        )


def _member_ids(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    return [str(m["value"]) for m in items if isinstance(m, dict) and m.get("value")]


async def list_groups(ctx: ServiceContext, filter_: str | None, start: int, count: int) -> dict[str, Any]:
    stmt = select(Workspace)
    if filter_:
        m = FILTER.match(filter_)
        if not m or m.group(1).lower() != "displayname":
            raise ScimError(400, "only displayName eq filters are supported for groups", "invalidFilter")
        stmt = stmt.where(Workspace.name == m.group(2))
    total = await ctx.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    start = max(start, 1)
    rows = await ctx.session.scalars(
        stmt.order_by(Workspace.name).offset(start - 1).limit(min(count, MAX_RESULTS))
    )
    return list_response([await group_resource(ctx.session, w) for w in rows.all()], total, start)


async def get_group(ctx: ServiceContext, group_id: str) -> dict[str, Any]:
    ws = await ctx.session.get(Workspace, _uuid(group_id))
    if ws is None:
        raise ScimError(404, "group not found")
    return await group_resource(ctx.session, ws)


async def create_group(ctx: ServiceContext, body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("displayName") or "").strip()[:200]
    if not name:
        raise ScimError(400, "displayName is required", "invalidValue")
    if await ctx.session.scalar(select(Workspace.id).where(Workspace.name == name)):
        raise ScimError(409, "a group with this displayName already exists", "uniqueness")
    slug = _slugify(name)
    if await ctx.session.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    ws = Workspace(id=uuid.uuid4(), tenant_id=ctx.tenant_id, name=name, slug=slug)
    ctx.session.add(ws)
    await ctx.session.flush()
    await _set_members(ctx, ws, _member_ids(body.get("members")), [])
    events.emit(ctx, "workspace.created", "workspace", ws.id, {"name": name, "source": "scim"})
    return await group_resource(ctx.session, ws)


async def patch_group(ctx: ServiceContext, group_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ws = await ctx.session.get(Workspace, _uuid(group_id))
    if ws is None:
        raise ScimError(404, "group not found")
    for op in body.get("Operations") or []:
        kind = str(op.get("op", "")).lower()
        path = (op.get("path") or "").strip()
        value = op.get("value")
        if path.lower().startswith("members"):
            m = re.match(r'members\[value eq "([^"]+)"\]', path, re.IGNORECASE)
            if kind == "add":
                await _set_members(ctx, ws, _member_ids(value), [])
            elif kind == "remove":
                await _set_members(ctx, ws, [], [m.group(1)] if m else _member_ids(value))
            elif kind == "replace":
                current = [
                    str(u)
                    for u in (
                        await ctx.session.scalars(
                            select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws.id)
                        )
                    ).all()
                ]
                await _set_members(ctx, ws, _member_ids(value), current)
        elif kind in ("add", "replace"):
            updates = value if not path and isinstance(value, dict) else {path: value}
            if updates.get("displayName"):
                ws.name = str(updates["displayName"])[:200]
            if "members" in updates:
                await _set_members(ctx, ws, _member_ids(updates["members"]), [])
    await ctx.session.flush()
    events.emit(ctx, "workspace.updated", "workspace", ws.id, {"source": "scim"})
    return await group_resource(ctx.session, ws)


async def replace_group(ctx: ServiceContext, group_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ws = await ctx.session.get(Workspace, _uuid(group_id))
    if ws is None:
        raise ScimError(404, "group not found")
    if body.get("displayName"):
        ws.name = str(body["displayName"])[:200]
    current = [
        str(u)
        for u in (
            await ctx.session.scalars(
                select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws.id)
            )
        ).all()
    ]
    wanted = _member_ids(body.get("members"))
    await _set_members(
        ctx, ws, [w for w in wanted if w not in current], [c for c in current if c not in wanted]
    )
    await ctx.session.flush()
    events.emit(ctx, "workspace.updated", "workspace", ws.id, {"source": "scim"})
    return await group_resource(ctx.session, ws)


async def delete_group(ctx: ServiceContext, group_id: str) -> None:
    """Groups map to workspaces, which own projects: deleting only removes the SCIM members."""
    ws = await ctx.session.get(Workspace, _uuid(group_id))
    if ws is None:
        raise ScimError(404, "group not found")
    from sqlalchemy import delete

    await ctx.session.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id))
    events.emit(ctx, "workspace.updated", "workspace", ws.id, {"source": "scim", "members_cleared": True})


SERVICE_PROVIDER_CONFIG: dict[str, Any] = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
    "documentationUri": "https://github.com/parabyte-ca/project-glasshaus/blob/main/docs/sso-scim.md",
    "patch": {"supported": True},
    "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
    "filter": {"supported": True, "maxResults": MAX_RESULTS},
    "changePassword": {"supported": False},
    "sort": {"supported": False},
    "etag": {"supported": False},
    "authenticationSchemes": [
        {
            "type": "oauthbearertoken",
            "name": "Bearer token",
            "description": "A SCIM token created in Admin > Provisioning.",
            "primary": True,
        }
    ],
}

RESOURCE_TYPES = [
    {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "User",
        "name": "User",
        "endpoint": "/Users",
        "schema": USER_SCHEMA,
    },
    {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "Group",
        "name": "Group",
        "endpoint": "/Groups",
        "schema": GROUP_SCHEMA,
    },
]

__all__ = ["Conflict", "InvalidInput", "ScimError"]
