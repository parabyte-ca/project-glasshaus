"""OAuth 2.1 grants for MCP clients: consent (web app), codes, rotating tokens, revocation.

The MCP server is the authorization server (it serves /authorize, /token, /register and the
metadata documents through the MCP SDK); the signed-in user approves requests in the web app,
which calls the consent functions here through the REST API.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import Scope
from glasshaus.core.schemas import Schema
from glasshaus.identity.security import sha256
from glasshaus.oauth.models import OAuthClient, OAuthGrant, OAuthRequest

ACCESS_PREFIX = "gha_"
REFRESH_PREFIX = "ghr_"
CODE_TTL = timedelta(minutes=10)
REQUEST_TTL = timedelta(minutes=15)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
ALL_SCOPES = [s.value for s in Scope]
DEFAULT_SCOPES = [Scope.READ.value, Scope.TASKS_WRITE.value]
SCOPE_LABELS = {
    Scope.READ.value: "Read projects, tasks, comments, time and reports you can see",
    Scope.TASKS_WRITE.value: "Create and change tasks, comments, dependencies and time entries",
    Scope.PROJECTS_WRITE.value: "Create and change projects, automations and project settings",
    Scope.ADMIN.value: "Administer the organization (only if you are an admin)",
}


def now() -> datetime:
    return datetime.now(UTC)


def new_secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- consent (REST)


class ConsentRequest(Schema):
    id: str
    client_name: str
    client_id: str
    redirect_host: str
    scopes: list[str]
    scope_labels: dict[str, str]
    expires_at: datetime


class ConsentDecision(Schema):
    approve: bool
    scopes: list[str] | None = None


class ConsentResult(Schema):
    redirect_to: str


class ConnectedApp(Schema):
    id: uuid.UUID
    client_id: str
    client_name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None


async def _pending(session: AsyncSession, request_id: str) -> tuple[OAuthRequest, OAuthClient]:
    req = await session.get(OAuthRequest, request_id)
    if req is None or req.expires_at <= now():
        raise NotFound("authorization request not found or expired; start again from your app")
    client = await session.get(OAuthClient, req.client_id)
    if client is None:
        raise NotFound("authorization request not found")
    return req, client


def _redirect(params: dict[str, Any], query: dict[str, str]) -> str:
    base = params["redirect_uri"]
    if params.get("state") is not None:
        query["state"] = params["state"]
    return f"{base}{'&' if '?' in base else '?'}{urlencode(query)}"


def _offerable(ctx: ServiceContext, scopes: list[str]) -> list[str]:
    """The admin scope is only offered to organization admins (as for API tokens)."""
    return [s for s in scopes if s != Scope.ADMIN.value or ctx.actor.is_org_admin]


async def get_consent(ctx: ServiceContext, request_id: str) -> ConsentRequest:
    if ctx.actor.user_id is None or ctx.actor.method != "session":
        raise PermissionDenied("sign in to the web app to approve access")
    req, client = await _pending(ctx.session, request_id)
    scopes = _offerable(ctx, req.params.get("scopes") or DEFAULT_SCOPES)
    return ConsentRequest(
        id=req.id,
        client_name=client.client_name or client.client_id,
        client_id=client.client_id,
        redirect_host=urlsplit(req.params["redirect_uri"]).netloc or req.params["redirect_uri"],
        scopes=scopes,
        scope_labels={s: SCOPE_LABELS.get(s, s) for s in scopes},
        expires_at=req.expires_at,
    )


async def decide(ctx: ServiceContext, request_id: str, decision: ConsentDecision) -> ConsentResult:
    """Approve (issue a one-time code bound to this user, tenant and PKCE challenge) or deny."""
    if ctx.actor.user_id is None or ctx.actor.method != "session":
        raise PermissionDenied("sign in to the web app to approve access")
    req, client = await _pending(ctx.session, request_id)
    params = req.params
    await ctx.session.delete(req)
    if not decision.approve:
        return ConsentResult(redirect_to=_redirect(params, {"error": "access_denied"}))
    requested = _offerable(ctx, params.get("scopes") or DEFAULT_SCOPES)
    granted = decision.scopes if decision.scopes is not None else requested
    if not granted or set(granted) - set(requested):
        raise InvalidInput("choose at least one of the requested permissions")
    code = new_secret()
    ctx.session.add(
        OAuthGrant(
            token_hash=sha256(code),
            kind="code",
            family_id=uuid.uuid4(),
            client_id=client.client_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.actor.user_id,
            scopes=sorted(granted),
            resource=params.get("resource"),
            code_challenge=params["code_challenge"],
            redirect_uri=params["redirect_uri"],
            redirect_uri_explicit=params.get("redirect_uri_provided_explicitly", True),
            expires_at=now() + CODE_TTL,
        )
    )
    await ctx.session.flush()
    return ConsentResult(redirect_to=_redirect(params, {"code": code}))


async def list_connected_apps(ctx: ServiceContext) -> list[ConnectedApp]:
    if ctx.actor.user_id is None:
        return []
    rows = await ctx.session.execute(
        select(OAuthGrant, OAuthClient.client_name)
        .join(OAuthClient, OAuthClient.client_id == OAuthGrant.client_id)
        .where(
            OAuthGrant.user_id == ctx.actor.user_id,
            OAuthGrant.kind == "refresh",
            OAuthGrant.revoked_at.is_(None),
            OAuthGrant.expires_at > now(),
        )
        .order_by(OAuthGrant.created_at.desc())
    )
    seen: set[uuid.UUID] = set()
    out = []
    for grant, name in rows.all():
        if grant.family_id in seen:
            continue
        seen.add(grant.family_id)
        out.append(
            ConnectedApp(
                id=grant.family_id,
                client_id=grant.client_id,
                client_name=name or grant.client_id,
                scopes=grant.scopes,
                created_at=grant.created_at,
                last_used_at=grant.last_used_at,
            )
        )
    return out


async def revoke_app(ctx: ServiceContext, family_id: uuid.UUID) -> None:
    result = await ctx.session.execute(
        update(OAuthGrant)
        .where(OAuthGrant.family_id == family_id, OAuthGrant.user_id == ctx.actor.user_id)
        .values(revoked_at=now())
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise NotFound("connected app not found")


# --------------------------------------------------------------------------- tokens


async def actor_from_access_token(session: AsyncSession, raw: str) -> tuple[Actor, OAuthGrant] | None:
    """Resolve an OAuth access token to the acting user (scopes as granted)."""
    from glasshaus.identity.models import User

    if not raw.startswith(ACCESS_PREFIX):
        return None
    grant = await session.get(OAuthGrant, sha256(raw))
    if grant is None or grant.kind != "access" or grant.revoked_at is not None or grant.expires_at <= now():
        return None
    from glasshaus.db import apply_tenant

    await apply_tenant(session, grant.tenant_id)
    user = await session.get(User, grant.user_id)
    if user is None or not user.is_active or user.kind == "assistant":
        return None
    if grant.last_used_at is None or now() - grant.last_used_at > timedelta(minutes=5):
        grant.last_used_at = now()
        await session.execute(
            update(OAuthGrant)
            .where(OAuthGrant.family_id == grant.family_id, OAuthGrant.kind == "refresh")
            .values(last_used_at=now())
        )
    actor = Actor(
        tenant_id=grant.tenant_id,
        user_id=user.id,
        org_role=user.org_role,
        method="oauth",
        scopes=frozenset(grant.scopes),
        client=f"oauth:{grant.client_id}",
    )
    return actor, grant


def issue_pair(base: OAuthGrant, scopes: list[str]) -> tuple[str, str, list[OAuthGrant]]:
    """New access + refresh token in the same consent family."""
    access, refresh = new_secret(ACCESS_PREFIX), new_secret(REFRESH_PREFIX)
    common: dict[str, Any] = {
        "family_id": base.family_id,
        "client_id": base.client_id,
        "tenant_id": base.tenant_id,
        "user_id": base.user_id,
        "scopes": sorted(scopes),
        "resource": base.resource,
    }
    rows = [
        OAuthGrant(token_hash=sha256(access), kind="access", expires_at=now() + ACCESS_TTL, **common),
        OAuthGrant(token_hash=sha256(refresh), kind="refresh", expires_at=now() + REFRESH_TTL, **common),
    ]
    return access, refresh, rows


async def purge_expired() -> int:
    """Housekeeping (worker cron): drop expired requests and grants that ended over a day ago."""
    from glasshaus.db import system_session

    cutoff = now() - timedelta(days=1)
    async with system_session() as session:
        a = await session.execute(delete(OAuthRequest).where(OAuthRequest.expires_at < now()))
        b = await session.execute(delete(OAuthGrant).where(OAuthGrant.expires_at < cutoff))
        return int(a.rowcount or 0) + int(b.rowcount or 0)  # type: ignore[attr-defined]
