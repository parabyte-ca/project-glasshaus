"""Password hashing, JWT access tokens and opaque secrets."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from glasshaus.config import get_settings
from glasshaus.core.rbac import OrgRole

_hasher = PasswordHasher()
# Verified against when the user does not exist, so timing doesn't reveal valid emails.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
API_TOKEN_PREFIX = "ghp_"  # noqa: S105 - public prefix, not a secret
JWT_ISSUER = "glasshaus"
JWT_AUDIENCE = "glasshaus-api"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_api_token() -> tuple[str, str]:
    """Return (raw token, display prefix)."""
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[: len(API_TOKEN_PREFIX) + 6]


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID, org_role: OrgRole, session_id: uuid.UUID
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": org_role.value,
        "sid": str(session_id),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(claims, get_settings().secret_key.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        get_settings().secret_key.get_secret_value(),
        algorithms=["HS256"],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        options={"require": ["exp", "sub", "tid", "sid"]},
    )
    return claims
