"""Shared schema helpers."""

import base64

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(None, description="Opaque cursor for the next page; null when done.")


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        kind, value = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        offset = int(value)
    except (ValueError, UnicodeDecodeError) as exc:
        from glasshaus.core.errors import InvalidInput

        raise InvalidInput("invalid cursor") from exc
    if kind != "o" or offset < 0:
        from glasshaus.core.errors import InvalidInput

        raise InvalidInput("invalid cursor")
    return offset
