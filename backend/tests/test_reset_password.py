"""``glasshaus reset-password``: for when nobody can sign in to reset a password in the app."""

import io
import sys

import pytest
from httpx import AsyncClient

from glasshaus import cli
from glasshaus.redis_client import get_redis
from tests.factories import PASSWORD, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

NEW = "a brand new passphrase 42"


async def login(client: AsyncClient, world, password: str):  # type: ignore[no-untyped-def]
    client.cookies.clear()
    return await client.post(
        "/api/v1/auth/login",
        json={"email": world.owner.email, "password": password, "organization": world.tenant.slug},
    )


async def test_reset_sets_the_password_ends_sessions_and_clears_lockout(client: AsyncClient) -> None:
    world = await make_world()
    assert (await login(client, world, PASSWORD)).status_code == 200
    cookies = dict(client.cookies)
    await get_redis().set(f"glasshaus:login-account:{world.owner.email.lower()}", 99)  # locked out

    await cli._reset_password(world.owner.email, NEW)

    assert (await login(client, world, PASSWORD)).status_code == 401  # the old one is gone
    assert (await login(client, world, NEW)).status_code == 200  # and the lockout with it
    client.cookies.clear()
    for k, v in cookies.items():  # the browser that was signed in before is signed out
        client.cookies.set(k, v)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_reset_refuses_an_unknown_address_and_a_weak_password(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await make_world()
    with pytest.raises(SystemExit):
        await cli._reset_password("nobody@example.invalid", NEW)
    monkeypatch.setattr(sys, "stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit):
        cli.cmd_reset_password(type("Args", (), {"email": world.owner.email, "password_stdin": True})())
