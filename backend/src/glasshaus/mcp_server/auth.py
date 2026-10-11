"""OAuth 2.1 authorization server for MCP clients (PKCE, dynamic client registration, rotating
refresh tokens) backed by Postgres, plus bearer verification for OAuth and personal API tokens.

The SDK serves /authorize, /token, /register, /revoke and the RFC 8414 / RFC 9728 metadata.
/authorize sends the user to the web app's consent page; approving there issues the code.
"""

import secrets
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import update

from glasshaus.config import get_settings
from glasshaus.core.context import Actor
from glasshaus.core.errors import Unauthenticated
from glasshaus.db import system_session
from glasshaus.identity.security import API_TOKEN_PREFIX, sha256
from glasshaus.oauth import service as oauth
from glasshaus.oauth.models import OAuthClient, OAuthGrant, OAuthRequest


def _ts(dt: Any) -> int:
    return int(dt.timestamp())


def actor_claims(actor: Actor) -> dict[str, Any]:
    return {
        "tenant_id": str(actor.tenant_id),
        "user_id": str(actor.user_id) if actor.user_id else None,
        "org_role": actor.org_role.value,
        "method": actor.method,
        "client": actor.client,
    }


def _for_this_server(resource: str) -> bool:
    public = get_settings().mcp_public_url.rstrip("/")
    return resource.rstrip("/").lower() in {public.lower(), f"{public}/mcp".lower()}


async def resolve_bearer(raw: str) -> tuple[Actor, AccessToken] | None:
    """Personal API token (``ghp_``) or OAuth access token (``gha_``) -> acting user."""
    from glasshaus.identity import service as identity

    async with system_session() as session:
        if raw.startswith(API_TOKEN_PREFIX):
            try:
                actor = await identity.actor_from_api_token(session, raw)
            except Unauthenticated:
                return None
            token = AccessToken(
                token=raw,
                client_id=actor.client or "api-token",
                scopes=sorted(actor.scopes or []),
                subject=str(actor.user_id),
                claims=actor_claims(actor),
            )
            return actor, token
        resolved = await oauth.actor_from_access_token(session, raw)
        if resolved is None:
            return None
        actor, grant = resolved
        if grant.resource and not _for_this_server(grant.resource):
            return None  # issued for another resource (RFC 8707 audience)
        token = AccessToken(
            token=raw,
            client_id=grant.client_id,
            scopes=list(grant.scopes),
            expires_at=_ts(grant.expires_at),
            resource=grant.resource,
            subject=str(grant.user_id),
            claims=actor_claims(actor),
        )
        return actor, token


LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}
UNSAFE_SCHEMES = {"javascript", "data", "vbscript", "file", "blob", "about", "filesystem"}


def safe_redirect_uri(uri: str) -> bool:
    """https anywhere, http only to this computer, or a native app's private scheme (``com.example:/cb``).
    Script-capable schemes (javascript:, data:) are refused: the consent page navigates to the result."""
    from urllib.parse import urlsplit

    if any(c.isspace() or ord(c) < 32 for c in uri):
        return False
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return (parts.hostname or "") in LOOPBACK
    return bool(scheme) and scheme not in UNSAFE_SCHEMES and "." in scheme


class GlasshausTokenVerifier:
    """Used when OAuth is unavailable (plain HTTP off localhost): API tokens only."""

    async def verify_token(self, token: str) -> AccessToken | None:
        resolved = await resolve_bearer(token)
        return resolved[1] if resolved and token.startswith(API_TOKEN_PREFIX) else None


class GlasshausOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with system_session() as session:
            row = await session.get(OAuthClient, client_id)
            if row is None:
                return None
            return OAuthClientInformationFull.model_validate(
                {**row.metadata_, "client_id": row.client_id, "client_secret": row.client_secret}
            )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if not safe_redirect_uri(str(uri)):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "redirect URIs must be https, http on this computer (localhost), or an app's own scheme",
                )
        data = client_info.model_dump(mode="json", exclude_none=True)
        data.pop("client_secret", None)
        async with system_session() as session:
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_secret=client_info.client_secret,
                    client_name=(client_info.client_name or "")[:200],
                    metadata_=data,
                )
            )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        scopes = params.scopes or oauth.DEFAULT_SCOPES
        if unknown := set(scopes) - set(oauth.ALL_SCOPES):
            raise AuthorizeError("invalid_scope", f"unknown scope {sorted(unknown)[0]}")
        request_id = secrets.token_urlsafe(24)
        async with system_session() as session:
            session.add(
                OAuthRequest(
                    id=request_id,
                    client_id=client.client_id,
                    params={**params.model_dump(mode="json"), "scopes": scopes},
                    expires_at=oauth.now() + oauth.REQUEST_TTL,
                )
            )
        return f"{get_settings().public_url.rstrip('/')}/oauth/consent?request={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with system_session() as session:
            grant = await session.get(OAuthGrant, sha256(authorization_code))
            if grant is not None and grant.kind == "code" and grant.revoked_at is not None:
                # A code used twice was intercepted: end the tokens issued from it (RFC 6749 §4.1.2).
                await session.execute(
                    update(OAuthGrant)
                    .where(OAuthGrant.family_id == grant.family_id, OAuthGrant.revoked_at.is_(None))
                    .values(revoked_at=oauth.now())
                )
                return None
        if grant is None or grant.kind != "code" or grant.client_id != client.client_id:
            return None
        assert grant.code_challenge is not None
        assert grant.redirect_uri is not None
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(grant.scopes),
            expires_at=grant.expires_at.timestamp(),
            client_id=grant.client_id,
            code_challenge=grant.code_challenge,
            redirect_uri=grant.redirect_uri,
            redirect_uri_provided_explicitly=bool(grant.redirect_uri_explicit),
            resource=grant.resource,
            subject=str(grant.user_id),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        async with system_session() as session:
            # Single use: claim the code atomically; a replay revokes the whole family.
            grant = await session.scalar(
                update(OAuthGrant)
                .where(
                    OAuthGrant.token_hash == sha256(authorization_code.code),
                    OAuthGrant.kind == "code",
                    OAuthGrant.revoked_at.is_(None),
                )
                .values(revoked_at=oauth.now())
                .returning(OAuthGrant)
            )
            if grant is None:
                raise TokenError("invalid_grant", "authorization code already used or revoked")
            access, refresh, rows = oauth.issue_pair(grant, list(grant.scopes))
            session.add_all(rows)
        return OAuthToken(
            access_token=access,
            expires_in=int(oauth.ACCESS_TTL.total_seconds()),
            scope=" ".join(sorted(grant.scopes)),
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with system_session() as session:
            grant = await session.get(OAuthGrant, sha256(refresh_token))
            if grant is None or grant.kind != "refresh" or grant.client_id != client.client_id:
                return None
            if grant.revoked_at is not None:
                # Reuse of a rotated refresh token: treat as theft and end the whole consent.
                await session.execute(
                    update(OAuthGrant)
                    .where(OAuthGrant.family_id == grant.family_id)
                    .values(revoked_at=oauth.now())
                )
                return None
            if grant.expires_at <= oauth.now():
                return None
        return RefreshToken(
            token=refresh_token,
            client_id=grant.client_id,
            scopes=list(grant.scopes),
            expires_at=_ts(grant.expires_at),
            resource=grant.resource,
            subject=str(grant.user_id),
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        async with system_session() as session:
            grant = await session.scalar(
                update(OAuthGrant)
                .where(
                    OAuthGrant.token_hash == sha256(refresh_token.token),
                    OAuthGrant.kind == "refresh",
                    OAuthGrant.revoked_at.is_(None),
                )
                .values(revoked_at=oauth.now())
                .returning(OAuthGrant)
            )
            if grant is None:
                raise TokenError("invalid_grant", "refresh token already used or revoked")
            granted = scopes or list(grant.scopes)
            if set(granted) - set(grant.scopes):
                raise TokenError("invalid_scope", "cannot widen scopes on refresh")
            # Old access tokens of this family stop working once rotated.
            await session.execute(
                update(OAuthGrant)
                .where(OAuthGrant.family_id == grant.family_id, OAuthGrant.kind == "access")
                .values(revoked_at=oauth.now())
            )
            access, refresh, rows = oauth.issue_pair(grant, granted)
            session.add_all(rows)
        return OAuthToken(
            access_token=access,
            expires_in=int(oauth.ACCESS_TTL.total_seconds()),
            scope=" ".join(sorted(granted)),
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        resolved = await resolve_bearer(token)
        return resolved[1] if resolved else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with system_session() as session:
            grant = await session.get(OAuthGrant, sha256(token.token))
            if grant is not None:
                await session.execute(
                    update(OAuthGrant)
                    .where(OAuthGrant.family_id == grant.family_id)
                    .values(revoked_at=oauth.now())
                )
