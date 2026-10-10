"""Single sign-on endpoints (browser redirects) and identity-provider administration."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response

from glasshaus.api.deps import ACCESS_COOKIE, CSRF_COOKIE, Ctx, Session, client_ip
from glasshaus.api.v1.auth import _set_cookies
from glasshaus.config import get_settings
from glasshaus.core.errors import ServiceError, Unauthenticated
from glasshaus.db import apply_tenant
from glasshaus.identity import security
from glasshaus.identity import service as identity
from glasshaus.identity.models import User
from glasshaus.logs import get_logger
from glasshaus.sso import oidc, saml
from glasshaus.sso import service as sso
from glasshaus.sso.models import IdentityProvider
from glasshaus.sso.service import LinkedIdentity, ProviderCreate, ProviderRead, ProviderUpdate, PublicProvider

router = APIRouter()
log = get_logger(__name__)
BROWSER_COOKIE = "gh_sso"  # ties a sign-in to the browser that started it (no login CSRF)


def _browser_cookie(response: Response, value: str) -> None:
    secure = get_settings().public_url.startswith("https://")
    # SAML answers with a cross-site POST, which only carries SameSite=None cookies (needs https).
    response.set_cookie(
        BROWSER_COOKIE,
        value,
        max_age=sso.STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        path="/api/v1/auth/sso",
    )


def _check_browser(request: Request, flow: dict[str, str]) -> None:
    import secrets

    nonce = request.cookies.get(BROWSER_COOKIE, "")
    if not nonce or not secrets.compare_digest(security.sha256(nonce), flow.get("browser", "")):
        raise Unauthenticated("sign-in was started in another browser; start again here")


def _fail(exc: ServiceError) -> RedirectResponse:
    log.info("sso.failed", detail=exc.detail)
    response = RedirectResponse(
        f"/?sso_error={quote(str(exc.detail))}", status_code=status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(BROWSER_COOKIE, path="/api/v1/auth/sso")
    return response


@router.get(
    "/auth/sso/providers",
    response_model=list[PublicProvider],
    tags=["auth"],
    summary="Single sign-on options for an organization (sign-in page)",
)
async def public_providers(session: Session, organization: str | None = None) -> list[PublicProvider]:
    return await sso.public_providers(session, organization)


@router.get(
    "/auth/sso/{organization}/{slug}/start",
    tags=["auth"],
    summary="Start single sign-on (redirects to the identity provider)",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def start(
    request: Request,
    organization: str,
    slug: str,
    session: Session,
    next: str | None = None,  # noqa: A002
    link: bool = Query(False, description="Link this provider to the signed-in account instead."),
    csrf: str | None = Query(
        None, description="With link=true: the CSRF token, so other sites cannot start it."
    ),
) -> Response:
    import secrets

    nonce = secrets.token_urlsafe(32)
    try:
        provider = await sso.provider_by_slug(session, organization, slug)
        target = sso.safe_next(next)
        extra: dict[str, str] = {"browser": security.sha256(nonce)}
        if link:
            user_id = await _signed_in_user(request, session, provider)
            expected = request.cookies.get(CSRF_COOKIE, "")
            if not expected or not csrf or not secrets.compare_digest(expected, csrf):
                raise Unauthenticated("start linking from Account in Glasshaus")
            extra, target = {**extra, "link_user_id": str(user_id)}, "/account?sso_linked=1"
        url = await (
            oidc.start(provider, target, extra)
            if provider.kind == "oidc"
            else saml.start(organization, provider, target, extra)
        )
    except ServiceError as exc:
        return _fail(exc)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    _browser_cookie(response, nonce)
    return response


async def _signed_in_user(request: Request, session: Session, provider: IdentityProvider) -> uuid.UUID:
    cookie = request.cookies.get(ACCESS_COOKIE)
    if not cookie:
        raise Unauthenticated("sign in first, then link single sign-on from Account")
    actor = await identity.actor_from_access_token(session, cookie)
    if actor.tenant_id != provider.tenant_id or actor.user_id is None:
        raise Unauthenticated("sign in to this organization first")
    return actor.user_id


async def _complete(
    request: Request,
    session: Session,
    provider: IdentityProvider,
    flow: dict[str, str],
    identity_claims: tuple[str, str | None, str | None, bool],
) -> Response:
    subject, email, name, verified = identity_claims
    if flow.get("link_user_id"):
        # Linking from Account: the browser must still be signed in as the user who started it.
        user_id = await _signed_in_user(request, session, provider)
        if str(user_id) != flow["link_user_id"]:
            raise Unauthenticated("sign in as the account you are linking, then try again")
        linked = await session.get(User, user_id)
        if linked is None:
            raise Unauthenticated("account not found")
        await sso.link_identity(session, provider, linked, subject=subject)
        return RedirectResponse(flow["next"], status_code=status.HTTP_303_SEE_OTHER)
    user = await sso.resolve_user(
        session, provider, subject=subject, email=email, name=name, email_verified=verified
    )
    result = await identity._issue_session(
        session, user, user_agent=request.headers.get("user-agent", ""), ip=client_ip(request)
    )
    response = RedirectResponse(flow["next"], status_code=status.HTTP_303_SEE_OTHER)
    _set_cookies(response, result)
    return response


async def _provider_for(session: Session, state: dict[str, str], kind: str) -> IdentityProvider:
    if state.get("kind") != kind:
        raise Unauthenticated("sign-in expired; start again")
    await apply_tenant(session, uuid.UUID(state["tenant_id"]))
    provider = await session.get(IdentityProvider, uuid.UUID(state["provider_id"]))
    if provider is None or not provider.enabled:
        raise Unauthenticated("identity provider is no longer available")
    return provider


@router.get("/auth/sso/oidc/callback", tags=["auth"], summary="OIDC redirect URI", include_in_schema=True)
async def oidc_callback(
    request: Request,
    session: Session,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = Query(None, max_length=500),
) -> Response:
    try:
        flow = await sso.take_state(state)
        _check_browser(request, flow)
        provider = await _provider_for(session, flow, "oidc")
        if error or not code:
            raise Unauthenticated(error_description or error or "sign-in was cancelled")
        claims = await oidc.finish(provider, flow, code)
        return await _complete(request, session, provider, flow, claims)
    except ServiceError as exc:
        return _fail(exc)


@router.post("/auth/sso/saml/acs", tags=["auth"], summary="SAML assertion consumer service (HTTP-POST)")
async def saml_acs(
    request: Request,
    session: Session,
    SAMLResponse: str = Form(..., max_length=1_000_000),  # noqa: N803 - SAML binding field name
    RelayState: str = Form(..., max_length=200),  # noqa: N803
) -> Response:
    try:
        flow = await sso.take_state(RelayState)
        _check_browser(request, flow)
        provider = await _provider_for(session, flow, "saml")
        subject, email, name = await saml.finish(provider, flow, SAMLResponse)
        # SAML has no verified-email flag; existing accounts link only when the provider trusts it.
        return await _complete(request, session, provider, flow, (subject, email, name, False))
    except ServiceError as exc:
        return _fail(exc)


@router.get(
    "/auth/sso/saml/{organization}/{slug}/metadata",
    tags=["auth"],
    summary="SAML service provider metadata",
    response_class=Response,
    responses={200: {"content": {"application/samlmetadata+xml": {}}}},
)
async def saml_metadata(organization: str, slug: str, session: Session) -> Response:
    provider = await sso.provider_by_slug(session, organization, slug)
    if provider.kind != "saml":
        raise Unauthenticated("not a SAML provider")
    return Response(saml.metadata_xml(organization, provider), media_type="application/samlmetadata+xml")


# --------------------------------------------------------------------------- administration


@router.get(
    "/admin/sso-providers",
    response_model=list[ProviderRead],
    tags=["admin"],
    summary="List identity providers",
)
async def list_providers(ctx: Ctx) -> list[ProviderRead]:
    return await sso.list_providers(ctx)


@router.post(
    "/admin/sso-providers",
    response_model=ProviderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    summary="Add an OIDC or SAML identity provider",
)
async def create_provider(ctx: Ctx, data: ProviderCreate) -> ProviderRead:
    return await sso.create_provider(ctx, data)


@router.patch(
    "/admin/sso-providers/{provider_id}",
    response_model=ProviderRead,
    tags=["admin"],
    summary="Update an identity provider",
)
async def update_provider(ctx: Ctx, provider_id: uuid.UUID, data: ProviderUpdate) -> ProviderRead:
    return await sso.update_provider(ctx, provider_id, data)


@router.delete(
    "/admin/sso-providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin"],
    summary="Remove an identity provider",
)
async def delete_provider(ctx: Ctx, provider_id: uuid.UUID) -> Response:
    await sso.delete_provider(ctx, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/auth/sso/identities",
    response_model=list[LinkedIdentity],
    tags=["auth"],
    summary="Single sign-on identities linked to your account",
)
async def my_identities(ctx: Ctx) -> list[LinkedIdentity]:
    return await sso.my_identities(ctx)
