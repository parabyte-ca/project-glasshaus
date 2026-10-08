"""Outbound automation webhooks: SSRF-checked, IP-pinned, HMAC-signed.

The host is resolved once, every address is checked, and the request connects to the checked
address (TLS still verifies the original host name), so DNS rebinding cannot redirect it.
Redirects are never followed.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import orjson

from glasshaus.config import get_settings
from glasshaus.version import __version__

SIGNATURE_HEADER = "X-Glasshaus-Signature"
IP = ipaddress.IPv4Address | ipaddress.IPv6Address
# Cloud metadata endpoints outside the link-local range (AWS IPv6, Alibaba).
_METADATA = {ipaddress.ip_address("fd00:ec2::254"), ipaddress.ip_address("100.100.100.200")}


class WebhookRefused(Exception):
    pass


@dataclass
class Delivery:
    url: str
    ok: bool
    status_code: int | None = None
    error: str | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def check_address(ip: IP, *, allow_private: bool) -> None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip in _METADATA:
        raise WebhookRefused(f"address {ip} is not allowed")
    if ip.is_reserved or (not ip.is_global and not allow_private):
        raise WebhookRefused(f"private address {ip} is not allowed (set GLASSHAUS_WEBHOOK_ALLOW_PRIVATE)")


async def resolve(host: str, port: int) -> IP:
    """Resolve and check every address; return the first (all must pass)."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses: list[IP] = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise WebhookRefused(f"cannot resolve {host}") from exc
        addresses = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
    if not addresses:
        raise WebhookRefused(f"cannot resolve {host}")
    allow_private = get_settings().webhook_allow_private
    for ip in addresses:
        check_address(ip, allow_private=allow_private)
    return addresses[0]


def sign(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


async def send(
    url: str, payload: dict[str, Any], *, secret: str | None, event: str = "automation"
) -> Delivery:
    started = time.monotonic()
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise WebhookRefused("only http(s) URLs are allowed")
        if parts.username or parts.password:
            raise WebhookRefused("credentials in webhook URLs are not allowed")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = await resolve(parts.hostname, port)
        pinned_host = f"[{ip}]" if ip.version == 6 else str(ip)
        pinned = urlunsplit((parts.scheme, f"{pinned_host}:{port}", parts.path or "/", parts.query, ""))
        body = orjson.dumps(payload)
        timestamp = int(time.time())
        headers = {
            "Host": parts.netloc,
            "Content-Type": "application/json",
            "User-Agent": f"Glasshaus/{__version__}",
            "X-Glasshaus-Event": event,
            "X-Glasshaus-Delivery": str(uuid.uuid4()),
        }
        if secret:
            headers[SIGNATURE_HEADER] = sign(secret, timestamp, body)
        async with httpx.AsyncClient(
            timeout=get_settings().webhook_timeout_seconds, follow_redirects=False, trust_env=False
        ) as client:
            request = client.build_request(
                "POST", pinned, content=body, headers=headers, extensions={"sni_hostname": parts.hostname}
            )
            response = await client.send(request)
        ok = 200 <= response.status_code < 300
        return Delivery(
            url=url,
            ok=ok,
            status_code=response.status_code,
            error=None if ok else f"HTTP {response.status_code}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except WebhookRefused as exc:
        return Delivery(url=url, ok=False, error=str(exc))
    except httpx.HTTPError as exc:
        return Delivery(
            url=url,
            ok=False,
            error=f"{type(exc).__name__}: {exc}"[:500],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
