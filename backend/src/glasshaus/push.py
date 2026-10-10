"""Web Push: phone and desktop notifications through the browser's own push service.

People turn it on per device (Account > Notifications on this device). The browser gives us an
endpoint at its push service (Google, Apple, Mozilla or Microsoft) and two keys; every message is
encrypted for that device (RFC 8291, aes128gcm) and signed with this server's VAPID key (RFC 8292),
which is derived from GLASSHAUS_SECRET_KEY, so there is nothing to configure or store.

A worker job sends a push for each new in-app notification of someone with a subscribed device.
Only push service hosts are accepted as endpoints (a subscription cannot point the server at an
internal address), and dead subscriptions (404/410) are removed.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import http_ece  # type: ignore[import-untyped]
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from pydantic import Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, delete, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.config import get_settings
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, RateLimited
from glasshaus.core.orm import Base, TenantScoped, UUIDPk, utcnow
from glasshaus.core.schemas import Schema
from glasshaus.logs import get_logger

log = get_logger(__name__)

# Push services browsers use. Endpoints anywhere else are refused.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    ".push.apple.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
)
MAX_PER_RUN = 300
MAX_AGE = timedelta(minutes=10)  # older notifications are not pushed (the person has moved on)
MAX_DEVICES = 10  # per person; the oldest go first
SEND_CONCURRENCY = 20
TESTS_PER_MINUTE = 3


class PushSubscription(UUIDPk, TenantScoped, Base):
    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    device: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class PushKeys(Schema):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscriptionCreate(Schema):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: PushKeys
    device: str = Field("", max_length=200, description="A label such as the browser and system.")


class PushStatus(Schema):
    public_key: str = Field(description="VAPID application server key (base64url) for pushManager.subscribe.")
    devices: int = Field(description="How many of your devices get notifications.")


# --- keys ----------------------------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def vapid_key() -> ec.EllipticCurvePrivateKey:
    """This server's VAPID key, derived from the secret key (stable across restarts)."""
    secret = get_settings().secret_key.get_secret_value().encode()
    order = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    seed = hmac.new(secret, b"glasshaus web push vapid key", hashlib.sha256).digest()
    return ec.derive_private_key(int.from_bytes(seed, "big") % (order - 1) + 1, ec.SECP256R1())


def public_key() -> str:
    point = (
        vapid_key()
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return _b64(point)


def _vapid_header(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": get_settings().public_url
        if get_settings().public_url.startswith("https://")
        else f"mailto:{get_settings().admin_email}",
    }
    header = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    der = vapid_key().sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = f"{header}.{body}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={public_key()}"


def allowed_endpoint(endpoint: str) -> bool:
    # No whitespace or control characters: the URL parsers must agree on the host.
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint):
        return False
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return False
    try:
        if httpx.URL(endpoint).host.lower() != host:
            return False
    except (httpx.InvalidURL, ValueError):
        return False
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


# --- subscriptions -------------------------------------------------------------------------------


def _user(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise InvalidInput("notifications belong to a person")
    return ctx.actor.user_id


async def status(ctx: ServiceContext) -> PushStatus:
    count = await ctx.session.scalar(
        select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == _user(ctx))
    )
    return PushStatus(public_key=public_key(), devices=int(count or 0))


async def subscribe(ctx: ServiceContext, data: PushSubscriptionCreate) -> PushStatus:
    if not allowed_endpoint(data.endpoint):
        raise InvalidInput("not a browser push service address")
    try:
        point = _unb64(data.keys.p256dh)
        if len(point) != 65 or len(_unb64(data.keys.auth)) != 16:
            raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)  # a real curve point
    except ValueError:
        raise InvalidInput("invalid push keys") from None
    user_id = _user(ctx)
    from sqlalchemy.dialects.postgresql import insert

    from glasshaus.db import system_session

    # An endpoint belongs to one browser profile. If someone else signed in there before, it moves
    # to this person, but only with the same keys (proof it is that browser, not a guessed address).
    async with system_session() as session:
        stmt = insert(PushSubscription).values(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            endpoint=data.endpoint,
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
            device=data.device,
        )
        moved = await session.scalar(
            stmt.on_conflict_do_update(
                index_elements=[PushSubscription.endpoint],
                set_={
                    "tenant_id": stmt.excluded.tenant_id,
                    "user_id": stmt.excluded.user_id,
                    "device": stmt.excluded.device,
                    "failures": 0,
                },
                where=(PushSubscription.p256dh == stmt.excluded.p256dh)
                & (PushSubscription.auth == stmt.excluded.auth),
            ).returning(PushSubscription.id)
        )
        if moved is None:
            raise Conflict("this device is already registered with different keys; turn it off and on again")
        # Keep the newest few devices per person.
        keep = (
            select(PushSubscription.id)
            .where(PushSubscription.user_id == user_id)
            .order_by(PushSubscription.created_at.desc())
            .limit(MAX_DEVICES)
        )
        await session.execute(
            delete(PushSubscription).where(
                PushSubscription.user_id == user_id, PushSubscription.id.not_in(keep)
            )
        )
    return await status(ctx)


async def unsubscribe(ctx: ServiceContext, endpoint: str) -> None:
    sub = await ctx.session.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == endpoint, PushSubscription.user_id == _user(ctx)
        )
    )
    if sub is None:
        raise NotFound("this device is not subscribed")
    await ctx.session.delete(sub)
    await ctx.session.flush()


# --- sending -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    url: str
    tag: str


@dataclass(frozen=True)
class Target:
    id: uuid.UUID
    endpoint: str
    p256dh: str
    auth: str


def encrypt(target: Target, payload: bytes) -> bytes:
    return http_ece.encrypt(  # type: ignore[no-any-return]
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_unb64(target.p256dh),
        auth_secret=_unb64(target.auth),
        version="aes128gcm",
    )


async def deliver(client: httpx.AsyncClient, target: Target, message: Message) -> int:
    """Send one push; returns the HTTP status (0 when it could not be sent)."""
    if not allowed_endpoint(target.endpoint):
        return 0
    payload = json.dumps(
        {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag}
    ).encode()
    try:
        r = await client.post(
            target.endpoint,
            content=encrypt(target, payload),
            headers={
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": "86400",
                "Urgency": "normal",
                "Authorization": _vapid_header(target.endpoint),
            },
        )
    except Exception as exc:  # noqa: BLE001 - one bad device must not stop the others
        log.warning("push.failed", error=type(exc).__name__)
        return 0
    return r.status_code


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, follow_redirects=False)


async def send_to(user_targets: list[tuple[Target, Message]]) -> dict[str, int]:
    """Send pushes outside any transaction, then record the outcomes (dead subscriptions go)."""

    if not user_targets:
        return {"sent": 0, "failed": 0, "removed": 0}
    results: list[tuple[Target, int]] = []
    gate = asyncio.Semaphore(SEND_CONCURRENCY)

    async def one(client: httpx.AsyncClient, target: Target, message: Message) -> None:
        async with gate:
            results.append((target, await deliver(client, target, message)))

    try:
        async with _client() as client:
            await asyncio.gather(*(one(client, t, m) for t, m in user_targets))
    finally:
        # Record what was sent even when the job is cut short, so dead devices still get removed.
        counts = await _record(results)
    return counts


async def _record(results: list[tuple["Target", int]]) -> dict[str, int]:
    from glasshaus.db import system_session

    sent = failed = removed = 0
    now = datetime.now(UTC)
    async with system_session() as session:
        for target, code in results:
            if 200 <= code < 300:
                sent += 1
                await session.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == target.id)
                    .values(last_success_at=now, failures=0)
                )
            elif code in (404, 410):
                removed += 1
                await session.execute(delete(PushSubscription).where(PushSubscription.id == target.id))
            else:
                failed += 1
                await session.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == target.id)
                    .values(failures=PushSubscription.failures + 1)
                )
        # Give up on a device after many failures in a row.
        await session.execute(delete(PushSubscription).where(PushSubscription.failures >= 20))
    return {"sent": sent, "failed": failed, "removed": removed}


async def push_new_notifications(now: datetime | None = None) -> dict[str, int]:
    """Worker job: push each new in-app notification to its person's subscribed devices, once."""
    from glasshaus.collab.models import Notification
    from glasshaus.db import system_session
    from glasshaus.identity.models import User
    from glasshaus.projects.models import Project

    now = now or datetime.now(UTC)
    work: list[tuple[Target, Message]] = []
    async with system_session() as session:
        rows = (
            await session.execute(
                select(Notification, Project.key)
                .outerjoin(Project, Project.id == Notification.project_id)
                .where(
                    Notification.pushed_at.is_(None),
                    Notification.created_at >= now - MAX_AGE,
                    Notification.user_id.in_(
                        select(PushSubscription.user_id)
                        .join(User, User.id == PushSubscription.user_id)
                        .where(User.is_active.is_(True))
                    ),
                )
                .order_by(Notification.created_at)
                .limit(MAX_PER_RUN)
                .with_for_update(of=Notification, skip_locked=True)
            )
        ).all()
        if not rows:
            return {"sent": 0, "failed": 0, "removed": 0}
        users = {n.user_id for n, _ in rows}
        targets: dict[uuid.UUID, list[Target]] = {}
        for sub in (
            await session.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(users)))
        ).all():
            targets.setdefault(sub.user_id, []).append(Target(sub.id, sub.endpoint, sub.p256dh, sub.auth))
        for n, key in rows:
            n.pushed_at = now
            url = n.link or (f"/projects/{key}?task={n.task_id}" if key and n.task_id else "/")
            message = Message(title="Glasshaus", body=n.title, url=url, tag=str(n.id))
            work.extend((t, message) for t in targets.get(n.user_id, []))
    return await send_to(work)


async def send_test(actor: Actor) -> dict[str, int]:
    """Send a test notification to every device of the person asking."""
    from glasshaus.db import unit_of_work
    from glasshaus.redis_client import get_redis

    key = f"glasshaus:push:test:{actor.tenant_id}:{actor.user_id}:{int(time.time() // 60)}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 90)
    except Exception:
        count = 0
        log.warning("push.rate_limit_unavailable", exc_info=True)
    if count > TESTS_PER_MINUTE:
        raise RateLimited("too many test notifications; try again in a minute")
    async with unit_of_work(actor) as ctx:
        user_id = _user(ctx)
        subs = (
            await ctx.session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
        ).all()
        targets = [Target(s.id, s.endpoint, s.p256dh, s.auth) for s in subs]
    if not targets:
        raise NotFound("none of your devices get notifications yet")
    message = Message(
        title="Glasshaus", body="Notifications work on this device.", url="/account", tag="test"
    )
    return await send_to([(t, message) for t in targets])
