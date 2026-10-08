"""@mention parsing.

Supported forms: ``@[Display Name](user:<uuid>)`` (what the UI inserts) and ``@email``.
"""

import re
import uuid

from sqlalchemy import func, select

from glasshaus.core.context import ServiceContext
from glasshaus.identity.models import User

TOKEN_RE = re.compile(r"@\[[^\]]{1,200}\]\(user:([0-9a-fA-F-]{36})\)")
EMAIL_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
MAX_MENTIONS = 50


async def extract_mentions(ctx: ServiceContext, body: str) -> list[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for raw in TOKEN_RE.findall(body):
        try:
            ids.add(uuid.UUID(raw))
        except ValueError:
            continue
    emails = {e.lower() for e in EMAIL_RE.findall(body)}
    if emails:
        rows = await ctx.session.scalars(select(User.id).where(func.lower(User.email).in_(emails)))
        ids.update(rows.all())
    if not ids:
        return []
    known = await ctx.session.scalars(select(User.id).where(User.id.in_(list(ids)[:MAX_MENTIONS])))
    return sorted(known.all(), key=str)
