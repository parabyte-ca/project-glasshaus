"""Client address behind the web container's proxy.

Forwarded headers are believed only when the connection comes from a trusted proxy (by default the
`web` container and loopback), so clients that reach the API port directly cannot choose their
address for login throttling, rate limits or the audit log. Hostnames are resolved and cached.
"""

import ipaddress
import socket
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from glasshaus.config import get_settings
from glasshaus.logs import get_logger

log = get_logger(__name__)
Network = ipaddress.IPv4Network | ipaddress.IPv6Network
REFRESH_SECONDS = 30.0


class TrustedProxies:
    def __init__(self, entries: list[str]) -> None:
        self.entries = entries
        self.networks: list[Network] = []
        self.expires = 0.0

    def _resolve(self) -> list[Network]:
        networks: list[Network] = []
        for entry in self.entries:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
                continue
            except ValueError:
                pass
            try:
                for info in socket.getaddrinfo(entry, None):
                    networks.append(ipaddress.ip_network(info[4][0]))
            except OSError:
                pass  # e.g. `web` outside Docker
        return networks

    def contains(self, host: str) -> bool:
        now = time.monotonic()
        if now >= self.expires:
            self.networks, self.expires = self._resolve(), now + REFRESH_SECONDS
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address in network for network in self.networks)


class ProxyHeadersMiddleware:
    """Use the right-most X-Forwarded-For address, which the trusted proxy itself appended."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.trusted = TrustedProxies(get_settings().trusted_proxies)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
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
