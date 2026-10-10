"""Shared schema helpers."""

import base64
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    # Response schemas list defaulted fields as required (they are always present), so generated
    # clients get accurate types; request schemas keep them optional.
    model_config = ConfigDict(
        from_attributes=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(None, description="Opaque cursor for the next page; null when done.")


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def encode_keyset(when: datetime, row_id: uuid.UUID) -> str:
    """Cursor for newest-first lists: continue after this (time, id)."""
    return base64.urlsafe_b64encode(f"k:{when.isoformat()}|{row_id}".encode()).decode()


def decode_keyset(cursor: str | None) -> tuple[datetime, uuid.UUID] | int | None:
    """A keyset position, or an offset from an older cursor (still accepted), or None to start."""
    if not cursor:
        return None
    try:
        kind, value = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        if kind == "k":
            when, row_id = value.split("|", 1)
            return datetime.fromisoformat(when), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        from glasshaus.core.errors import InvalidInput

        raise InvalidInput("invalid cursor") from exc
    return decode_cursor(cursor)


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
