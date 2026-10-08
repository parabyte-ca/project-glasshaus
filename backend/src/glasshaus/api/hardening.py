"""HTTP hardening for the API (it can be reached directly on its own port, not only through nginx):
security headers, a request-size cap, and a per-principal rate limit (Redis, fails open)."""

import hashlib
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from glasshaus.config import get_settings
from glasshaus.logs import get_logger

log = get_logger(__name__)
MAX_BODY_BYTES = 10 * 1024 * 1024
API_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
]
# JSON and file responses only; the Swagger UI at /api/docs loads its own scripts.
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


def _principal(scope: Scope) -> str:
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"")
    if auth:
        return "t:" + hashlib.sha256(auth).hexdigest()[:24]
    cookie = headers.get(b"cookie", b"")
    for part in cookie.split(b";"):
        name, _, value = part.strip().partition(b"=")
        if name == b"gh_access" and value:
            return "s:" + hashlib.sha256(value).hexdigest()[:24]
    client = scope.get("client")
    return "ip:" + (client[0] if client else "unknown")


class HardeningMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            await _reply(
                send, 413, b'{"code":"payload_too_large","detail":"request body too large","status":413}'
            )
            return
        if (
            path.startswith(("/api/", "/scim/"))
            and not path.startswith("/api/docs")
            and await _limited(scope)
        ):
            await _reply(
                send,
                429,
                b'{"code":"rate_limited","detail":"too many requests; slow down","status":429}',
                extra=[(b"retry-after", b"60")],
            )
            return
        secure = get_settings().public_url.startswith("https://")
        docs = path.startswith("/api/docs") or path == "/api/v1/openapi.json"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                added = [h for h in API_HEADERS if h[0] not in existing]
                if not docs and API_CSP[0] not in existing:
                    added.append(API_CSP)
                if b"cache-control" not in existing and path.startswith(("/api/v1/", "/scim/")):
                    added.append((b"cache-control", b"no-store"))
                if secure:
                    added.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = [*message.get("headers", []), *added]
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Every request also counts against its client address, at a higher limit (offices share an
# address), so inventing a new Authorization header per request does not escape the limit.
PER_ADDRESS_FACTOR = 5


async def _limited(scope: Scope) -> bool:
    limit = get_settings().api_rate_limit_per_minute
    if limit <= 0:
        return False
    from glasshaus.redis_client import get_redis

    minute = int(time.time() // 60)
    client = scope.get("client")
    keys = [
        (f"glasshaus:api:rl:{_principal(scope)}:{minute}", limit),
        (f"glasshaus:api:rl:addr:{client[0] if client else 'unknown'}:{minute}", limit * PER_ADDRESS_FACTOR),
    ]
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        for key, _ in keys:
            pipe.incr(key)
            pipe.expire(key, 90)
        counts = (await pipe.execute())[::2]
    except Exception:
        log.warning("api.rate_limit_unavailable", exc_info=True)
        return False
    return any(int(count) > cap for count, (_, cap) in zip(counts, keys, strict=True))


async def _reply(
    send: Send, status: int, body: bytes, extra: list[tuple[bytes, bytes]] | None = None
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
                *API_HEADERS,
                *(extra or []),
            ],
        }
    )  #
    await send({"type": "http.response.body", "body": body})
