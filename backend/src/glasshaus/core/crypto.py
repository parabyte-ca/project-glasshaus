"""Encryption at rest for third-party secrets (SSO client secrets, integration credentials).

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from GLASSHAUS_SECRET_KEY by HKDF, so no extra
setting is needed. Rotating the secret key makes stored secrets unreadable: re-enter them afterwards.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from glasshaus.config import get_settings
from glasshaus.core.errors import InvalidInput

PREFIX = "enc:v1:"


@lru_cache
def _fernet() -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"glasshaus", info=b"secrets-at-rest").derive(
        get_settings().secret_key.get_secret_value().encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str) -> str:
    return PREFIX + _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext.startswith(PREFIX):
        raise InvalidInput("stored secret is not encrypted")
    try:
        return _fernet().decrypt(ciphertext[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise InvalidInput("stored secret cannot be decrypted (was GLASSHAUS_SECRET_KEY changed?)") from exc


def mask(secret: str | None) -> str | None:
    """What the API shows for a stored secret: whether one is set, never its value."""
    return "••••••••" if secret else None
