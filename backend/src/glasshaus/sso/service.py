"""Single sign-on: identity-provider administration, the OIDC and SAML sign-in flows, account linking
and just-in-time provisioning.

Flow state (PKCE verifier, nonce, SAML request id, where to return) lives in Redis for 10 minutes,
keyed by an unguessable ``state`` value that comes back from the provider.
"""

import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import orjson
from pydantic import Field, HttpUrl, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.config import get_settings
from glasshaus.core import crypto, events
from glasshaus.core.authz import require_org
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, Unauthenticated
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.core.schemas import Schema
from glasshaus.identity.models import User
from glasshaus.sso.models import IdentityProvider, UserIdentity

STATE_TTL_SECONDS = 600
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,253}$")
SLUG = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
Kind = Literal["oidc", "saml"]


# --------------------------------------------------------------------------- schemas


class OidcConfig(Schema):
    issuer: HttpUrl = Field(description="Issuer URL; /.well-known/openid-configuration is read from it.")
    client_id: str = Field(min_length=1, max_length=300)
    scopes: str = Field("openid email profile", max_length=500)
    email_claim: str = Field("email", max_length=100)
    name_claim: str = Field("name", max_length=100)


class SamlConfig(Schema):
    idp_entity_id: str = Field(min_length=1, max_length=500)
    sso_url: HttpUrl = Field(description="IdP single sign-on URL (HTTP-Redirect binding).")
    idp_certificate: str = Field(
        min_length=100, max_length=20_000, description="IdP signing certificate (PEM)."
    )
    email_attribute: str | None = Field(
        None, max_length=300, description="Attribute holding the email; the NameID is used when empty."
    )
    name_attribute: str | None = Field(None, max_length=300)

    @field_validator("idp_certificate")
    @classmethod
    def _pem(cls, v: str) -> str:
        from cryptography import x509

        v = v.strip()
        if "BEGIN CERTIFICATE" not in v:
            v = "-----BEGIN CERTIFICATE-----\n" + v + "\n-----END CERTIFICATE-----"
        try:
            x509.load_pem_x509_certificate(v.encode())
        except ValueError as exc:
            raise ValueError("not a valid PEM certificate") from exc
        return v


class ProviderBase(Schema):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    allowed_domains: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Email domains this provider may sign in or create (empty: any).",
    )
    jit_provisioning: bool = Field(True, description="Create accounts on first sign-in.")
    default_role: Literal["member", "guest", "admin"] = "member"
    enforce: bool = Field(False, description="Require SSO for everyone except owners.")
    link_existing_accounts: bool = Field(
        False,
        description="Link a first sign-in to an existing member or guest account with the same email even "
        "when the IdP does not mark the address verified (SAML, Entra ID). Needs allowed domains. Owner "
        "and admin accounts are never linked this way; they link from Account settings.",
    )

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        return sorted({d.strip().lower().lstrip("@") for d in v if d.strip()})


class ProviderCreate(ProviderBase):
    slug: str = Field(pattern=SLUG)
    kind: Kind
    oidc: OidcConfig | None = None
    saml: SamlConfig | None = None
    client_secret: str | None = Field(None, max_length=500, description="OIDC client secret (write-only).")


class ProviderUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    enabled: bool | None = None
    allowed_domains: list[str] | None = Field(None, max_length=50)
    jit_provisioning: bool | None = None
    default_role: Literal["member", "guest", "admin"] | None = None
    enforce: bool | None = None
    link_existing_accounts: bool | None = None
    oidc: OidcConfig | None = None
    saml: SamlConfig | None = None
    client_secret: str | None = Field(None, max_length=500, description="Set to replace; '' to clear.")

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else sorted({d.strip().lower().lstrip("@") for d in v if d.strip()})


class ProviderRead(ProviderBase):
    id: uuid.UUID
    slug: str
    kind: Kind
    oidc: OidcConfig | None
    saml: SamlConfig | None
    client_secret_set: bool
    start_url: str
    redirect_uri: str | None = Field(description="OIDC: register this redirect URI at the provider.")
    sp_entity_id: str | None = Field(description="SAML: the service provider entity ID (audience).")
    acs_url: str | None = Field(description="SAML: assertion consumer service URL.")
    metadata_url: str | None = Field(description="SAML: service provider metadata.")
    created_at: datetime


class PublicProvider(Schema):
    name: str
    slug: str
    kind: Kind
    start_url: str


# --------------------------------------------------------------------------- urls


def _base() -> str:
    return get_settings().public_url.rstrip("/")


def oidc_redirect_uri() -> str:
    return f"{_base()}/api/v1/auth/sso/oidc/callback"


def saml_acs_url() -> str:
    return f"{_base()}/api/v1/auth/sso/saml/acs"


def saml_entity_id(org: str, slug: str) -> str:
    return f"{_base()}/api/v1/auth/sso/saml/{org}/{slug}/metadata"


def start_url(org: str, slug: str) -> str:
    return f"/api/v1/auth/sso/{org}/{slug}/start"


async def _org_slug(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    from glasshaus.models import Tenant

    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    return tenant.slug


def _read(p: IdentityProvider, org: str) -> ProviderRead:
    return ProviderRead(
        id=p.id,
        name=p.name,
        slug=p.slug,
        kind=p.kind,
        enabled=p.enabled,
        allowed_domains=list(p.allowed_domains),
        jit_provisioning=p.jit_provisioning,
        default_role=p.default_role,
        enforce=p.enforce,
        link_existing_accounts=p.link_existing_accounts,
        oidc=OidcConfig.model_validate(p.config) if p.kind == "oidc" else None,
        saml=SamlConfig.model_validate(p.config) if p.kind == "saml" else None,
        client_secret_set=bool(p.client_secret),
        start_url=start_url(org, p.slug),
        redirect_uri=oidc_redirect_uri() if p.kind == "oidc" else None,
        sp_entity_id=saml_entity_id(org, p.slug) if p.kind == "saml" else None,
        acs_url=saml_acs_url() if p.kind == "saml" else None,
        metadata_url=saml_entity_id(org, p.slug) if p.kind == "saml" else None,
        created_at=p.created_at,
    )


# --------------------------------------------------------------------------- administration


def _config(kind: str, oidc: OidcConfig | None, saml: SamlConfig | None) -> dict[str, Any]:
    if kind == "oidc":
        if oidc is None:
            raise InvalidInput("an OIDC provider needs oidc settings")
        return oidc.model_dump(mode="json")
    if saml is None:
        raise InvalidInput("a SAML provider needs saml settings")
    return saml.model_dump(mode="json")


async def list_providers(ctx: ServiceContext) -> list[ProviderRead]:
    require_org(ctx, Permission.ORG_MANAGE)
    org = await _org_slug(ctx.session, ctx.tenant_id)
    rows = await ctx.session.scalars(select(IdentityProvider).order_by(IdentityProvider.name))
    return [_read(p, org) for p in rows.all()]


async def create_provider(ctx: ServiceContext, data: ProviderCreate) -> ProviderRead:
    require_org(ctx, Permission.ORG_MANAGE)
    provider = IdentityProvider(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=data.name,
        slug=data.slug,
        kind=data.kind,
        enabled=data.enabled,
        config=_config(data.kind, data.oidc, data.saml),
        client_secret=crypto.encrypt(data.client_secret) if data.client_secret else None,
        allowed_domains=data.allowed_domains,
        jit_provisioning=data.jit_provisioning,
        default_role=data.default_role,
        enforce=data.enforce,
        link_existing_accounts=data.link_existing_accounts,
    )
    _check_linking(provider)
    ctx.session.add(provider)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a provider with this slug already exists") from exc
    result = _read(provider, await _org_slug(ctx.session, ctx.tenant_id))
    events.emit(ctx, "sso.provider_created", "identity_provider", provider.id, _audit_view(result))
    return result


def _check_linking(p: IdentityProvider) -> None:
    if p.link_existing_accounts and not p.allowed_domains:
        raise InvalidInput("linking existing accounts by email needs at least one allowed domain")


def _audit_view(p: ProviderRead) -> dict[str, Any]:
    return p.model_dump(
        mode="json",
        include={"name", "slug", "kind", "enabled", "enforce", "allowed_domains", "link_existing_accounts"},
    )


async def _provider(ctx: ServiceContext, provider_id: uuid.UUID) -> IdentityProvider:
    p = await ctx.session.get(IdentityProvider, provider_id)
    if p is None:
        raise NotFound("identity provider not found")
    return p


async def update_provider(ctx: ServiceContext, provider_id: uuid.UUID, data: ProviderUpdate) -> ProviderRead:
    require_org(ctx, Permission.ORG_MANAGE)
    p = await _provider(ctx, provider_id)
    changes = data.model_dump(exclude_unset=True)
    for field in (
        "name",
        "enabled",
        "allowed_domains",
        "jit_provisioning",
        "default_role",
        "enforce",
        "link_existing_accounts",
    ):
        if field in changes and changes[field] is not None:
            setattr(p, field, changes[field])
    if p.kind == "oidc" and data.oidc is not None:
        p.config = data.oidc.model_dump(mode="json")
    if p.kind == "saml" and data.saml is not None:
        p.config = data.saml.model_dump(mode="json")
    if data.client_secret is not None:
        p.client_secret = crypto.encrypt(data.client_secret) if data.client_secret else None
    _check_linking(p)
    await ctx.session.flush()
    result = _read(p, await _org_slug(ctx.session, ctx.tenant_id))
    events.emit(ctx, "sso.provider_updated", "identity_provider", p.id, _audit_view(result))
    return result


async def delete_provider(ctx: ServiceContext, provider_id: uuid.UUID) -> None:
    require_org(ctx, Permission.ORG_MANAGE)
    p = await _provider(ctx, provider_id)
    await ctx.session.delete(p)
    events.emit(ctx, "sso.provider_deleted", "identity_provider", provider_id, {"slug": p.slug})


# --------------------------------------------------------------------------- sign-in support


async def public_providers(session: AsyncSession, organization: str | None) -> list[PublicProvider]:
    from glasshaus.db import apply_tenant
    from glasshaus.models import Tenant

    slug = organization or get_settings().default_tenant_slug
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        return []
    await apply_tenant(session, tenant.id)
    rows = await session.scalars(
        select(IdentityProvider).where(IdentityProvider.enabled.is_(True)).order_by(IdentityProvider.name)
    )
    return [
        PublicProvider(name=p.name, slug=p.slug, kind=p.kind, start_url=start_url(slug, p.slug))
        for p in rows.all()
    ]


async def password_login_allowed(session: AsyncSession, user: User) -> bool:
    if user.org_role == OrgRole.OWNER:
        return True
    enforced = await session.scalar(
        select(func.count())
        .select_from(IdentityProvider)
        .where(IdentityProvider.enabled.is_(True), IdentityProvider.enforce.is_(True))
    )
    return not enforced


async def provider_by_slug(session: AsyncSession, organization: str, slug: str) -> IdentityProvider:
    from glasshaus.db import apply_tenant
    from glasshaus.models import Tenant

    tenant = await session.scalar(select(Tenant).where(Tenant.slug == organization))
    if tenant is None:
        raise NotFound("identity provider not found")
    await apply_tenant(session, tenant.id)
    p = await session.scalar(select(IdentityProvider).where(IdentityProvider.slug == slug))
    if p is None or not p.enabled:
        raise NotFound("identity provider not found")
    return p


def safe_next(next_path: str | None) -> str:
    """Only same-site relative paths, so the sign-in flow cannot be used as an open redirect."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//") or "\\" in next_path:
        return "/"
    parts = urlsplit(next_path)
    return parts.path + (f"?{parts.query}" if parts.query else "")


async def save_state(data: dict[str, Any]) -> str:
    from glasshaus.redis_client import get_redis

    state = secrets.token_urlsafe(32)
    await get_redis().set(f"glasshaus:sso:state:{state}", orjson.dumps(data), ex=STATE_TTL_SECONDS)
    return state


async def take_state(state: str | None) -> dict[str, Any]:
    from glasshaus.redis_client import get_redis

    if not state or len(state) > 100:
        raise Unauthenticated("sign-in expired; start again")
    raw = await get_redis().getdel(f"glasshaus:sso:state:{state}")
    if raw is None:
        raise Unauthenticated("sign-in expired; start again")
    data: dict[str, Any] = orjson.loads(raw)
    return data


async def remember_once(key: str, ttl_seconds: int) -> None:
    """Refuse replays (SAML assertion ids)."""
    from glasshaus.redis_client import get_redis

    if not await get_redis().set(f"glasshaus:sso:seen:{key}", b"1", ex=max(ttl_seconds, 60), nx=True):
        raise Unauthenticated("this sign-in response was already used")


async def resolve_user(
    session: AsyncSession,
    provider: IdentityProvider,
    *,
    subject: str,
    email: str | None,
    name: str | None,
    email_verified: bool = False,
) -> User:
    """Find the linked user, link an existing account by email, or create one (JIT).

    A first sign-in is linked to an existing account only when that is safe: never for owners (they
    link from Account settings), admins only when the IdP asserts the email is verified, members and
    guests when it is verified or the provider is set to trust its addresses (`link_existing_accounts`).
    """
    from glasshaus.audit.service import record_raw

    now = datetime.now(UTC)
    link = await session.scalar(
        select(UserIdentity).where(UserIdentity.provider_id == provider.id, UserIdentity.subject == subject)
    )
    user: User | None = None
    if link is not None:
        user = await session.get(User, link.user_id)
    else:
        if not email:
            raise Unauthenticated("the identity provider did not send an email address")
        # The IdP is trusted to assert addresses; homelab domains (.lan, .local, .home.arpa) are fine.
        email = email.strip()
        if not EMAIL.match(email):
            raise Unauthenticated("the identity provider sent an invalid email address")
        local, _, host = email.rpartition("@")
        email = f"{local}@{host.lower()}"
        domain = email.rsplit("@", 1)[-1].lower()
        if provider.allowed_domains and domain not in provider.allowed_domains:
            await record_raw(
                provider.tenant_id,
                "auth.sso_login",
                outcome="denied",
                method="sso",
                client=f"sso:{provider.slug}",
                detail={"email": email, "reason": "domain not allowed"},
            )
            raise Unauthenticated("your email domain is not allowed to sign in with this provider")
        user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is not None:
            reason = _link_refusal(provider, user, email_verified=email_verified)
            if reason:
                await record_raw(
                    provider.tenant_id,
                    "auth.sso_login",
                    outcome="denied",
                    actor_id=user.id,
                    method="sso",
                    client=f"sso:{provider.slug}",
                    detail={"email": email, "reason": reason},
                )
                raise Unauthenticated(
                    "an account with this email already exists; sign in with your password and link "
                    "single sign-on under Account, or ask an administrator"
                )
        if user is None:
            if not provider.jit_provisioning:
                raise Unauthenticated("no account exists for this email; ask an administrator to invite you")
            user = User(
                id=uuid.uuid4(),
                tenant_id=provider.tenant_id,
                email=email,
                name=(name or email.split("@")[0])[:200],
                org_role=OrgRole(provider.default_role),
                password_hash=None,
            )
            session.add(user)
            await session.flush()
            await record_raw(
                provider.tenant_id,
                "user.provisioned",
                outcome="ok",
                actor_id=user.id,
                method="sso",
                client=f"sso:{provider.slug}",
                target=f"user:{user.id}",
                detail={"email": email},
            )
        link = UserIdentity(
            tenant_id=provider.tenant_id, user_id=user.id, provider_id=provider.id, subject=subject
        )
        session.add(link)
    if user is None or not user.is_active:
        raise Unauthenticated("account disabled")
    link.last_login_at = now
    user.last_login_at = now
    await record_raw(
        provider.tenant_id,
        "auth.sso_login",
        outcome="ok",
        actor_id=user.id,
        method="sso",
        client=f"sso:{provider.slug}",
        detail={"email": user.email},
    )
    return user


def _link_refusal(provider: IdentityProvider, user: User, *, email_verified: bool) -> str | None:
    """Why a first sign-in may not be linked to this existing account (None: it may)."""
    if user.org_role == OrgRole.OWNER:
        return "owner accounts link single sign-on from Account settings"
    if user.org_role == OrgRole.ADMIN:
        return None if email_verified else "admin accounts need an email the IdP marks verified"
    if email_verified or (provider.link_existing_accounts and provider.allowed_domains):
        return None
    return "email not verified by the identity provider"


async def link_identity(
    session: AsyncSession, provider: IdentityProvider, user: User, *, subject: str
) -> None:
    """Link an IdP subject to the signed-in user (Account > Single sign-on)."""
    from glasshaus.audit.service import record_raw

    existing = await session.scalar(
        select(UserIdentity).where(UserIdentity.provider_id == provider.id, UserIdentity.subject == subject)
    )
    if existing is not None and existing.user_id != user.id:
        raise Conflict("this identity is already linked to another account")
    if existing is None:
        session.add(
            UserIdentity(
                tenant_id=provider.tenant_id, user_id=user.id, provider_id=provider.id, subject=subject
            )
        )
        await session.flush()
    await record_raw(
        provider.tenant_id,
        "auth.sso_linked",
        outcome="ok",
        actor_id=user.id,
        method="session",
        client=f"sso:{provider.slug}",
        target=f"user:{user.id}",
    )


class LinkedIdentity(Schema):
    """An enabled identity provider and whether it is linked to your account."""

    provider_name: str
    provider_slug: str
    kind: Kind
    linked: bool
    linked_at: datetime | None
    last_login_at: datetime | None
    link_url: str = Field(description="Open in the browser while signed in to link this provider.")


async def my_identities(ctx: ServiceContext) -> list[LinkedIdentity]:
    org = await _org_slug(ctx.session, ctx.tenant_id)
    providers = (
        await ctx.session.scalars(
            select(IdentityProvider).where(IdentityProvider.enabled.is_(True)).order_by(IdentityProvider.name)
        )
    ).all()
    links = {
        i.provider_id: i
        for i in (
            await ctx.session.scalars(select(UserIdentity).where(UserIdentity.user_id == ctx.actor.user_id))
        ).all()
    }
    result = []
    for p in providers:
        i = links.get(p.id)
        result.append(
            LinkedIdentity(
                provider_name=p.name,
                provider_slug=p.slug,
                kind=p.kind,
                linked=i is not None,
                linked_at=i.created_at if i else None,
                last_login_at=i.last_login_at if i else None,
                link_url=start_url(org, p.slug) + "?link=true",
            )
        )
    return result
