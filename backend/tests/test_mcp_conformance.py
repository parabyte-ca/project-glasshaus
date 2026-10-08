"""MCP conformance over real Streamable HTTP: discovery metadata, the 401 challenge, OAuth 2.1
(dynamic client registration, PKCE, consent in the web app, rotating refresh tokens, revocation),
API-token auth, and tool/resource/prompt listing. This is what VS Code, Claude and Copilot do.
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from glasshaus.config import get_settings
from tests.factories import PASSWORD, World, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

REDIRECT = "http://127.0.0.1:33418/callback"
AGENT_SCRIPT = Path(__file__).resolve().parents[2] / "examples" / "agent.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
async def mcp_url() -> AsyncIterator[str]:
    """The MCP HTTP app served by uvicorn on a free port, in the test event loop."""
    port = _free_port()
    base = f"http://localhost:{port}"
    settings = get_settings()
    old = settings.mcp_public_url
    settings.mcp_public_url = base  # issuer and resource URLs follow the address clients use
    from glasshaus.mcp_server import server as server_module

    server_module.server = server_module.build_server()
    app = server_module.create_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    while not srv.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)
    try:
        yield base
    finally:
        srv.should_exit = True
        await task
        settings.mcp_public_url = old
        server_module.server = server_module.build_server()


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def mcp_client(url: str, token: str) -> Client:
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return Client(streamable_http_client(f"{url}/mcp", http_client=http))


async def login(web: httpx.AsyncClient, world: World) -> dict[str, str]:
    r = await web.post(
        "/api/v1/auth/login",
        json={"email": world.owner.email, "password": PASSWORD, "organization": world.tenant.slug},
    )
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": web.cookies["gh_csrf"]}


async def register(http: httpx.AsyncClient, url: str) -> dict[str, Any]:
    r = await http.post(
        f"{url}/register",
        json={
            "client_name": "Conformance client",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": "read tasks:write",
        },
    )
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def authorize(
    http: httpx.AsyncClient,
    web: httpx.AsyncClient,
    csrf: dict[str, str],
    url: str,
    client_id: str,
    **decision: Any,
) -> tuple[str, str]:
    verifier, challenge = pkce()
    r = await http.get(
        f"{url}/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "read tasks:write",
            "resource": f"{url}/mcp",
        },
    )
    assert r.status_code == 302, r.text
    consent = urlsplit(r.headers["location"])
    assert consent.path == "/oauth/consent"
    request_id = parse_qs(consent.query)["request"][0]

    shown = await web.get(f"/api/v1/oauth/requests/{request_id}")
    assert shown.status_code == 200, shown.text
    assert shown.json()["client_name"] == "Conformance client"
    assert sorted(shown.json()["scopes"]) == ["read", "tasks:write"]

    decided = await web.post(
        f"/api/v1/oauth/requests/{request_id}", json={"approve": True, **decision}, headers=csrf
    )
    assert decided.status_code == 200, decided.text
    back = urlsplit(decided.json()["redirect_to"])
    query = parse_qs(back.query)
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT and query["state"] == ["xyz"]
    return query["code"][0], verifier


async def token(http: httpx.AsyncClient, url: str, **form: str) -> httpx.Response:
    return await http.post(f"{url}/token", data=form)


async def test_discovery_and_challenge(mcp_url: str) -> None:
    async with httpx.AsyncClient() as http:
        r = await http.post(f"{mcp_url}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        challenge = r.headers["www-authenticate"]
        assert challenge.startswith("Bearer") and "resource_metadata=" in challenge

        prm = (await http.get(f"{mcp_url}/.well-known/oauth-protected-resource/mcp")).json()
        assert prm["resource"].rstrip("/") == f"{mcp_url}/mcp"
        assert [s.rstrip("/") for s in prm["authorization_servers"]] == [mcp_url]

        meta = (await http.get(f"{mcp_url}/.well-known/oauth-authorization-server")).json()
        assert meta["issuer"].rstrip("/") == mcp_url
        assert meta["code_challenge_methods_supported"] == ["S256"]
        assert {"authorization_code", "refresh_token"} <= set(meta["grant_types_supported"])
        for endpoint in (
            "authorization_endpoint",
            "token_endpoint",
            "registration_endpoint",
            "revocation_endpoint",
        ):
            assert meta[endpoint].startswith(mcp_url)
        assert set(meta["scopes_supported"]) == {"read", "tasks:write", "projects:write", "admin"}

        assert (await http.get(f"{mcp_url}/healthz")).json() == {"status": "ok"}


async def test_oauth_flow_end_to_end(mcp_url: str, client: httpx.AsyncClient) -> None:
    world = await make_world()
    csrf = await login(client, world)
    async with httpx.AsyncClient() as http:
        reg = await register(http, mcp_url)
        assert "client_secret" not in reg or reg["client_secret"] is None
        code, verifier = await authorize(http, client, csrf, mcp_url, reg["client_id"])

        # PKCE: the wrong verifier is refused, and the code is single-use.
        bad = await token(
            http, mcp_url, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=reg["client_id"], code_verifier="x" * 50,
        )  # fmt: skip
        assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
        ok = await token(
            http, mcp_url, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=reg["client_id"], code_verifier=verifier,
        )  # fmt: skip
        assert ok.status_code == 200, ok.text
        tokens = ok.json()
        assert tokens["token_type"].lower() == "bearer" and tokens["access_token"].startswith("gha_")
        assert set(tokens["scope"].split()) == {"read", "tasks:write"}
        replay = await token(
            http, mcp_url, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=reg["client_id"], code_verifier=verifier,
        )  # fmt: skip
        assert replay.status_code == 400

        async with mcp_client(mcp_url, tokens["access_token"]) as mcp:
            me = await mcp.call_tool("whoami", {})
            assert me.structured_content is not None
            assert me.structured_content["user"]["id"] == str(world.owner.id)
            assert me.structured_content["client"] == f"oauth:{reg['client_id']}"
            created = await mcp.call_tool("create_task", {"project": world.project.key, "title": "Via OAuth"})
            assert not created.is_error
            denied = await mcp.call_tool("create_project", {"workspace": "main", "key": "NOPE", "name": "x"})
            assert denied.is_error  # projects:write was not granted

        apps = (await client.get("/api/v1/oauth/apps")).json()
        assert [a["client_name"] for a in apps] == ["Conformance client"]

        # Refresh rotates both tokens and retires the old access token.
        refreshed = await token(
            http, mcp_url, grant_type="refresh_token", refresh_token=tokens["refresh_token"],
            client_id=reg["client_id"],
        )  # fmt: skip
        assert refreshed.status_code == 200, refreshed.text
        new = refreshed.json()
        assert new["refresh_token"] != tokens["refresh_token"]
        stale = await http.post(
            f"{mcp_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert stale.status_code == 401
        async with mcp_client(mcp_url, new["access_token"]) as mcp:
            assert not (await mcp.call_tool("whoami", {})).is_error

        # Reusing the rotated refresh token is treated as theft: the whole grant is revoked.
        reuse = await token(
            http, mcp_url, grant_type="refresh_token", refresh_token=tokens["refresh_token"],
            client_id=reg["client_id"],
        )  # fmt: skip
        assert reuse.status_code == 400
        revoked = await http.post(
            f"{mcp_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {new['access_token']}"},
        )
        assert revoked.status_code == 401
        assert (await client.get("/api/v1/oauth/apps")).json() == []


async def test_consent_can_narrow_deny_and_disconnect(
    mcp_url: str, client: httpx.AsyncClient, app: Any
) -> None:
    world = await make_world()
    csrf = await login(client, world)
    async with httpx.AsyncClient() as http:
        reg = await register(http, mcp_url)
        code, verifier = await authorize(http, client, csrf, mcp_url, reg["client_id"], scopes=["read"])
        ok = await token(
            http, mcp_url, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=reg["client_id"], code_verifier=verifier,
        )  # fmt: skip
        assert ok.json()["scope"] == "read"
        access = ok.json()["access_token"]
        async with mcp_client(mcp_url, access) as mcp:
            result = await mcp.call_tool("create_task", {"project": world.project.key, "title": "x"})
            assert result.is_error

        app_id = (await client.get("/api/v1/oauth/apps")).json()[0]["id"]
        assert (await client.delete(f"/api/v1/oauth/apps/{app_id}", headers=csrf)).status_code == 204
        gone = await http.post(
            f"{mcp_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert gone.status_code == 401

        # Deny: the client gets error=access_denied with its state.
        _, challenge = pkce()
        r = await http.get(
            f"{mcp_url}/authorize",
            params={
                "response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT,
                "code_challenge": challenge, "code_challenge_method": "S256", "state": "s1",
            },
        )  # fmt: skip
        request_id = parse_qs(urlsplit(r.headers["location"]).query)["request"][0]
        denied = await client.post(
            f"/api/v1/oauth/requests/{request_id}", json={"approve": False}, headers=csrf
        )
        assert parse_qs(urlsplit(denied.json()["redirect_to"]).query) == {
            "error": ["access_denied"],
            "state": ["s1"],
        }

        # Consent needs a signed-in browser session, not an API token.
        r = await http.get(
            f"{mcp_url}/authorize",
            params={
                "response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT,
                "code_challenge": challenge, "code_challenge_method": "S256",
            },
        )  # fmt: skip
        request_id = parse_qs(urlsplit(r.headers["location"]).query)["request"][0]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            with_token = await api.get(f"/api/v1/oauth/requests/{request_id}", headers=world.headers)
        assert with_token.status_code == 403


async def test_api_token_and_listing_over_http(mcp_url: str) -> None:
    world = await make_world()
    async with mcp_client(mcp_url, await token_for(world.owner)) as mcp:
        tools = {t.name: t for t in (await mcp.list_tools()).tools}
        for name in ("create_task", "manage_dependencies", "status_summary", "log_time", "run_automation"):
            assert name in tools and tools[name].input_schema["type"] == "object"
        assert (
            tools["delete_tasks"].annotations is not None
            and tools["delete_tasks"].annotations.destructive_hint
        )
        assert "confirm" in tools["delete_tasks"].input_schema["properties"]
        templates = (await mcp.list_resource_templates()).resource_templates
        assert any(t.uri_template == "glasshaus://tasks/{ref}" for t in templates)
        assert len((await mcp.list_prompts()).prompts) == 4
        result = await mcp.call_tool("search_projects", {})
        assert not result.is_error
    with pytest.raises(Exception):  # noqa: B017 - the transport refuses with 401
        async with mcp_client(mcp_url, "ghp_not-a-real-token") as mcp:
            await mcp.list_tools()


async def test_example_agent_script(mcp_url: str) -> None:
    """examples/agent.py: create a task, link a dependency and pull a status summary over MCP."""
    world = await make_world()
    script = AGENT_SCRIPT
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script), "--url", f"{mcp_url}/mcp", "--project", world.project.key,
        env={**os.environ, "GLASSHAUS_TOKEN": await token_for(world.owner)},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    assert proc.returncode == 0, err.decode()
    result = json.loads(out)
    assert [t["key"] for t in result["summary"]["completed"]] == [result["design"]]
    assert b"waits for it" in err
