"""Phone notifications (Web Push) and the complete/reopen shortcuts."""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import http_ece  # type: ignore[import-untyped]
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from httpx import AsyncClient
from sqlalchemy import update

from glasshaus import push
from glasshaus.collab.models import Notification, NotificationKind
from glasshaus.collab.service import notify_users
from glasshaus.core.context import Actor
from glasshaus.db import system_session, unit_of_work
from tests.factories import auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Device:
    """A browser's side of a push subscription: its key pair and auth secret."""

    def __init__(self, name: str) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = f"https://fcm.googleapis.com/fcm/send/{name}-{os.urandom(4).hex()}"

    def body(self) -> dict[str, Any]:
        point = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return {
            "endpoint": self.endpoint,
            "keys": {"p256dh": b64(point), "auth": b64(self.auth)},
            "device": "Phone",
        }

    def read(self, body: bytes) -> dict[str, Any]:
        plain = http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth, version="aes128gcm")
        data: dict[str, Any] = json.loads(plain)
        return data


class PushService:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.status = 201

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.sent.append({"url": url, "content": content, "headers": headers})
        return httpx.Response(self.status)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> PushService:
    svc = PushService()

    class Client:
        async def __aenter__(self) -> PushService:
            return svc

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(push, "_client", Client)
    return svc


def check_vapid(header: str, endpoint: str) -> None:
    token, key = header.removeprefix("vapid t=").split(", k=")
    head, claims, sig = token.split(".")
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(key))
    raw = unb64(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong
    assert json.loads(unb64(claims))["aud"] == "https://fcm.googleapis.com" and key == push.public_key()


async def test_complete_and_reopen_can_be_repeated(client: AsyncClient) -> None:
    world = await make_world()
    task = await create_task(client, world)
    for _ in range(2):  # an offline phone may send it twice
        r = await client.post(f"/api/v1/tasks/{task['key']}/complete", headers=world.headers)
        assert r.status_code == 200 and r.json()["status"]["category"] == "done" and r.json()["completed_at"]
    r = await client.post(f"/api/v1/tasks/{task['id']}/reopen", headers=world.headers)
    assert r.json()["status"]["category"] == "todo" and r.json()["completed_at"] is None
    outsider = await make_user(world.tenant)
    r = await client.post(f"/api/v1/tasks/{task['id']}/complete", headers=auth(await token_for(outsider)))
    assert r.status_code == 404


async def test_subscribe_push_and_clean_up(client: AsyncClient, service: PushService) -> None:
    world = await make_world()
    status = (await client.get("/api/v1/push", headers=world.headers)).json()
    assert len(unb64(status["public_key"])) == 65 and status["devices"] == 0

    phone = Device("phone")
    bad = phone.body() | {"endpoint": "https://10.0.0.5/push"}
    assert (
        await client.post("/api/v1/push/subscriptions", json=bad, headers=world.headers)
    ).status_code == 422
    bad = phone.body() | {"endpoint": "http://fcm.googleapis.com/fcm/send/x"}
    assert (
        await client.post("/api/v1/push/subscriptions", json=bad, headers=world.headers)
    ).status_code == 422
    bad = phone.body() | {"keys": {"p256dh": "x" * 30, "auth": "y" * 10}}
    assert (
        await client.post("/api/v1/push/subscriptions", json=bad, headers=world.headers)
    ).status_code == 422
    r = await client.post("/api/v1/push/subscriptions", json=phone.body(), headers=world.headers)
    assert r.status_code == 201 and r.json()["devices"] == 1

    # A new notification is pushed once, encrypted for the device and signed with the VAPID key.
    async with unit_of_work(Actor.system(world.tenant.id)) as ctx:
        await notify_users(
            ctx,
            [world.owner.id],
            kind=NotificationKind.SYSTEM,
            title="Backups: <late>",
            link="/admin?tab=backups",
        )
    assert (await push.push_new_notifications())["sent"] >= 1
    mine = [s for s in service.sent if s["url"] == phone.endpoint]
    assert len(mine) == 1
    assert mine[0]["headers"]["Content-Encoding"] == "aes128gcm"
    check_vapid(mine[0]["headers"]["Authorization"], phone.endpoint)
    assert phone.read(mine[0]["content"]) | {"tag": ""} == {
        "title": "Glasshaus",
        "body": "Backups: <late>",
        "url": "/admin?tab=backups",
        "tag": "",
    }
    await push.push_new_notifications()
    assert len([s for s in service.sent if s["url"] == phone.endpoint]) == 1  # not twice

    # Old notifications are not pushed (the person has moved on).
    async with unit_of_work(Actor.system(world.tenant.id)) as ctx:
        await notify_users(ctx, [world.owner.id], kind=NotificationKind.SYSTEM, title="Old news")
    async with system_session() as session:
        await session.execute(
            update(Notification)
            .where(Notification.title == "Old news")
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
    await push.push_new_notifications()
    assert len([s for s in service.sent if s["url"] == phone.endpoint]) == 1

    # Test message; then the push service says the device is gone, and the subscription goes too.
    assert (await client.post("/api/v1/push/test", headers=world.headers)).json()["sent"] == 1
    service.status = 410
    assert (await client.post("/api/v1/push/test", headers=world.headers)).json()["removed"] == 1
    assert (await client.get("/api/v1/push", headers=world.headers)).json()["devices"] == 0
    assert (await client.post("/api/v1/push/test", headers=world.headers)).status_code == 404


async def test_a_device_belongs_to_whoever_signed_in_last(client: AsyncClient, service: PushService) -> None:
    world = await make_world()
    other = await make_user(world.tenant)
    other_headers = auth(await token_for(other))
    shared = Device("shared")
    await client.post("/api/v1/push/subscriptions", json=shared.body(), headers=world.headers)
    await client.post("/api/v1/push/subscriptions", json=shared.body(), headers=other_headers)
    assert (await client.get("/api/v1/push", headers=world.headers)).json()["devices"] == 0
    assert (await client.get("/api/v1/push", headers=other_headers)).json()["devices"] == 1
    gone = {"endpoint": shared.endpoint}
    r = await client.post("/api/v1/push/subscriptions/remove", json=gone, headers=world.headers)
    assert r.status_code == 404
    r = await client.post("/api/v1/push/subscriptions/remove", json=gone, headers=other_headers)
    assert r.status_code == 204


def test_only_push_services_are_allowed() -> None:
    assert push.allowed_endpoint("https://web.push.apple.com/abc")
    assert push.allowed_endpoint("https://updates.push.services.mozilla.com/wpush/v2/abc")
    assert push.allowed_endpoint("https://wns2-by3p.notify.windows.com/w/?token=abc")
    for url in (
        "https://evilpush.apple.com.example.com/x",
        "https://fcm.googleapis.com:8443/x",
        "https://user:pw@fcm.googleapis.com/x",
        "https://localhost/x",
        "https://push.apple.com.evil/x",
    ):
        assert not push.allowed_endpoint(url), url
