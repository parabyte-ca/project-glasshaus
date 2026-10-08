"""Single sign-on endpoints (browser redirects) and identity-provider administration."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response

from glasshaus.api.deps import Ctx, Session, client_ip
from glasshaus.api.v1.auth import _set_cookies
from glasshaus.core.errors import ServiceError, Unauthenticated
from glasshaus.db import apply_tenant
from glasshaus.identity import service as identity
from glasshaus.logs import get_logger
from glasshaus.sso import oidc, saml
from glasshaus.sso import service as sso
from glasshaus.sso.models import IdentityProvider
from glasshaus.sso.service import ProviderCreate, ProviderRead, ProviderUpdate, PublicProvider

router = APIRouter()
log = get_logger(__name__)


def _fail(exc: ServiceError) -> RedirectResponse:
    log.info("sso.failed", detail=exc.detail)
    return RedirectResponse(f"/?sso_error={quote(str(exc.detail))}", status_code=status.HTTP_303_SEE_OTHER)


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
async def start(organization: str, slug: str, session: Session, next: str | None = None) -> Response:  # noqa: A002
    try:
        provider = await sso.provider_by_slug(session, organization, slug)
        target = sso.safe_next(next)
        url = await (
            oidc.start(provider, target)
            if provider.kind == "oidc"
            else saml.start(organization, provider, target)
        )
    except ServiceError as exc:
        return _fail(exc)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


async def _complete(request: Request, session: Session, provider: IdentityProvider, subject: str,
                    email: str | None, name: str | None, next_path: str) -> Response:  # fmt: skip
    user = await sso.resolve_user(session, provider, subject=subject, email=email, name=name)
    result = await identity._issue_session(
        session, user, user_agent=request.headers.get("user-agent", ""), ip=client_ip(request)
    )
    response = RedirectResponse(next_path, status_code=status.HTTP_303_SEE_OTHER)
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
        provider = await _provider_for(session, flow, "oidc")
        if error or not code:
            raise Unauthenticated(error_description or error or "sign-in was cancelled")
        subject, email, name = await oidc.finish(provider, flow, code)
        return await _complete(request, session, provider, subject, email, name, flow["next"])
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
        provider = await _provider_for(session, flow, "saml")
        subject, email, name = await saml.finish(provider, flow, SAMLResponse)
        return await _complete(request, session, provider, subject, email, name, flow["next"])
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
