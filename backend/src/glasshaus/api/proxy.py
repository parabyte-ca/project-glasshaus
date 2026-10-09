"""Client address behind the web container's proxy.

Forwarded headers are believed only when the connection comes from a trusted proxy (by default the
`web` container and loopback), so clients that reach the API port directly cannot choose their
address for login throttling, rate limits or the audit log.

Hostnames are resolved in a background thread and cached; a request never waits for DNS. (Resolving
inline blocked the event loop: while `web` is not yet running, a slow resolver could stall every
request, health checks included, past their timeout, and an upgrade would roll back.)
"""

import asyncio
import ipaddress
import socket
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from glasshaus.config import get_settings
from glasshaus.logs import get_logger

log = get_logger(__name__)
Network = ipaddress.IPv4Network | ipaddress.IPv6Network
REFRESH_SECONDS = 30.0
RESOLVE_TIMEOUT_SECONDS = 5.0


class TrustedProxies:
    def __init__(self, entries: list[str]) -> None:
        self.literal: list[Network] = []
        self.hostnames: list[str] = []
        for entry in entries:
            try:
                self.literal.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                self.hostnames.append(entry)
        self.resolved: list[Network] = []
        self.expires = 0.0
        self._refreshing: asyncio.Task[None] | None = None

    def _resolve_hostnames(self) -> list[Network]:
        networks: list[Network] = []
        for name in self.hostnames:
            try:
                for info in socket.getaddrinfo(name, None):
                    networks.append(ipaddress.ip_network(info[4][0]))
            except OSError:
                pass  # e.g. `web` outside Docker, or not started yet
        return networks

    async def refresh(self) -> None:
        """Resolve the hostnames again (in a thread, with a time limit)."""
        self.expires = time.monotonic() + REFRESH_SECONDS
        if not self.hostnames:
            return
        try:
            self.resolved = await asyncio.wait_for(
                asyncio.to_thread(self._resolve_hostnames), RESOLVE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            log.warning("proxy.resolve_timeout", hostnames=self.hostnames)

    def refresh_soon(self) -> None:
        """Start a background refresh when the cache is stale; never wait for it."""
        if time.monotonic() < self.expires or (self._refreshing and not self._refreshing.done()):
            return
        self._refreshing = asyncio.get_running_loop().create_task(self.refresh())

    def contains(self, host: str) -> bool:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address in network for network in (*self.literal, *self.resolved))


class ProxyHeadersMiddleware:
    """Use the right-most X-Forwarded-For address, which the trusted proxy itself appended."""

    def __init__(self, app: ASGIApp, trusted: list[str] | None = None) -> None:
        self.app = app
        self.trusted = TrustedProxies(get_settings().trusted_proxies if trusted is None else trusted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            self.trusted.refresh_soon()
            client = scope.get("client")
            if client and self.trusted.contains(client[0]):
                headers = dict(scope.get("headers") or [])
                forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1")
                last = forwarded.split(",")[-1].strip() if forwarded else ""
                if last:
                    try:
                        ipaddress.ip_address(last)
                        scope = {**scope, "client": (last, client[1])}
                    except ValueError:
                        pass
        await self.app(scope, receive, send)
