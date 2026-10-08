"""OpenID Connect sign-in: authorization code flow with PKCE, state and nonce."""

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from glasshaus.core import crypto
from glasshaus.core.errors import Unauthenticated
from glasshaus.logs import get_logger
from glasshaus.sso.models import IdentityProvider
from glasshaus.sso.service import OidcConfig, oidc_redirect_uri, save_state

ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384", "EdDSA"]
log = get_logger(__name__)


def http_client() -> httpx.AsyncClient:
    """Replaced in tests with a mock transport."""
    return httpx.AsyncClient(timeout=10.0, follow_redirects=False)


async def discover(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with http_client() as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise Unauthenticated(f"identity provider discovery failed ({r.status_code})")
    meta: dict[str, Any] = r.json()
    if meta.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
        raise Unauthenticated("identity provider issuer does not match its configuration")
    return meta


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def start(provider: IdentityProvider, next_path: str, extra: dict[str, str] | None = None) -> str:
    cfg = OidcConfig.model_validate(provider.config)
    meta = await discover(str(cfg.issuer))
    verifier, challenge = _pkce()
    nonce = secrets.token_urlsafe(24)
    state = await save_state(
        {
            "kind": "oidc",
            "tenant_id": str(provider.tenant_id),
            "provider_id": str(provider.id),
            "verifier": verifier,
            "nonce": nonce,
            "next": next_path,
            **(extra or {}),
        }
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": oidc_redirect_uri(),
            "scope": cfg.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{meta['authorization_endpoint']}?{query}"


async def finish(
    provider: IdentityProvider, state: dict[str, Any], code: str
) -> tuple[str, str | None, str | None, bool]:
    """Exchange the code and validate the ID token. Returns (subject, email, name, email_verified)."""
    cfg = OidcConfig.model_validate(provider.config)
    meta = await discover(str(cfg.issuer))
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": oidc_redirect_uri(),
        "client_id": cfg.client_id,
        "code_verifier": state["verifier"],
    }
    if provider.client_secret:
        form["client_secret"] = crypto.decrypt(provider.client_secret)
    async with http_client() as client:
        r = await client.post(meta["token_endpoint"], data=form, headers={"Accept": "application/json"})
        if r.status_code != 200:
            log.warning("sso.oidc.token_failed", status=r.status_code, provider=provider.slug)
            raise Unauthenticated("the identity provider refused the sign-in")
        tokens = r.json()
        jwks = (await client.get(meta["jwks_uri"])).json()
    raw = tokens.get("id_token")
    if not raw:
        raise Unauthenticated("the identity provider did not return an ID token")
    try:
        header = jwt.get_unverified_header(raw)
        keys = jwt.PyJWKSet.from_dict(jwks)
        key = next((k for k in keys.keys if k.key_id == header.get("kid")), None) or (
            keys.keys[0] if len(keys.keys) == 1 else None
        )
        if key is None:
            raise Unauthenticated("ID token signed with an unknown key")
        claims: dict[str, Any] = jwt.decode(
            raw,
            key=key,
            algorithms=ALGORITHMS,
            audience=cfg.client_id,
            issuer=meta["issuer"],
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated(f"invalid ID token: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), state["nonce"]):
        raise Unauthenticated("invalid ID token: nonce mismatch")
    if claims.get("email_verified") in (False, "false"):
        raise Unauthenticated("your email address is not verified at the identity provider")
    email = claims.get(cfg.email_claim)
    name = claims.get(cfg.name_claim)
    # Only the standard `email` claim with email_verified=true proves the address; other claims
    # (preferred_username, upn) can be set by users at some IdPs.
    verified = cfg.email_claim == "email" and claims.get("email_verified") in (True, "true")
    return str(claims["sub"]), str(email) if email else None, str(name) if name else None, verified
