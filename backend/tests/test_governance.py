"""Governance: settings and retention, export, account recovery, sign-out, and the audit trail."""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from glasshaus.audit.handlers import record_event
from glasshaus.audit.models import AuditEntry
from glasshaus.collab.models import Notification
from glasshaus.core.rbac import OrgRole, Scope
from glasshaus.db import apply_tenant, system_session
from glasshaus.governance.service import apply_retention
from glasshaus.tasks.models import Task
from tests.factories import (
    PASSWORD,
    World,
    auth,
    backdate_audit,
    create_task,
    events_for,
    make_user,
    make_world,
    token_for,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def login(client: AsyncClient, world: World, email: str, password: str = PASSWORD) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password, "organization": world.tenant.slug}
    )
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.cookies["gh_csrf"]}


async def audit(world: World, action: str) -> list[AuditEntry]:
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        rows = await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.tenant_id == world.tenant.id, AuditEntry.action == action)
            .order_by(AuditEntry.created_at)
        )
        return list(rows.all())


async def test_settings_require_org_admin(client: AsyncClient) -> None:
    world = await make_world()
    member = auth(await token_for(await make_user(world.tenant)))
    assert (await client.get("/api/v1/admin/settings", headers=member)).status_code == 403
    current = (await client.get("/api/v1/admin/settings", headers=world.headers)).json()
    assert current["audit_retention_days"] == 365 and current["deleted_task_retention_days"] == 30
    r = await client.patch("/api/v1/admin/settings", json={"audit_retention_days": 30}, headers=world.headers)
    assert r.status_code == 200 and r.json()["audit_retention_days"] == 30
    bad = await client.patch(
        "/api/v1/admin/settings", json={"audit_retention_days": -1}, headers=world.headers
    )
    assert bad.status_code == 422


async def test_retention_purges_old_rows_only(client: AsyncClient) -> None:
    world = await make_world()
    await client.patch(
        "/api/v1/admin/settings",
        json={"audit_retention_days": 30, "notification_retention_days": 5, "deleted_task_retention_days": 7},
        headers=world.headers,
    )
    old, recent = (
        await create_task(client, world, title="old"),
        await create_task(client, world, title="recent"),
    )
    for t in (old, recent):
        assert (await client.delete(f"/api/v1/tasks/{t['id']}", headers=world.headers)).status_code in (
            200,
            204,
        )
    long_ago = datetime.now(UTC) - timedelta(days=40)
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        await session.execute(update(Task).where(Task.id == uuid.UUID(old["id"])).values(deleted_at=long_ago))
        session.add_all(
            [
                AuditEntry(tenant_id=world.tenant.id, actor_method="system", action="old", outcome="ok", detail={}),
                Notification(tenant_id=world.tenant.id, user_id=world.owner.id, kind="mention", title="old",
                             event_id=uuid.uuid4(), created_at=long_ago),
            ]
        )  # fmt: skip
    # The database stamps audit times; only its owner can backdate one (as time passing would).
    await backdate_audit(world, "old", long_ago)
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        session.add(AuditEntry(tenant_id=world.tenant.id, actor_method="system", action="new", outcome="ok"))
    result = await apply_retention()
    assert result.audit >= 1 and result.tasks >= 1 and result.notifications >= 1
    assert [e.action for e in await audit(world, "old")] == []
    assert len(await audit(world, "new")) == 1
    async with system_session() as session:
        remaining = set(
            (await session.scalars(select(Task.title).where(Task.project_id == world.project.id))).all()
        )
    assert remaining == {"recent"}


async def test_export_is_scoped_and_secret_free(client: AsyncClient) -> None:
    world, other = await make_world(), await make_world()
    await create_task(client, world, title="Mine")
    await create_task(client, other, title="Theirs")
    # Exports need a browser session.
    assert (await client.get("/api/v1/admin/export", headers=world.headers)).status_code == 403
    await login(client, world, world.owner.email)
    r = await client.get("/api/v1/admin/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["organization"]["slug"] == world.tenant.slug
    tasks = [json.loads(line) for line in archive.read("tasks.jsonl").splitlines()]
    assert [t["title"] for t in tasks] == ["Mine"]
    users = archive.read("users.jsonl").decode()
    assert "password_hash" not in users and world.owner.email in users
    assert "api_tokens.jsonl" in archive.namelist()
    assert "token_hash" not in archive.read("api_tokens.jsonl").decode()
    assert "auth_sessions.jsonl" not in archive.namelist()


async def test_password_reset_and_sign_out_everywhere(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    member_token = await token_for(member)
    # An admin with a browser session resets a member's password.
    csrf = await login(client, world, world.owner.email)
    r = await client.post(
        f"/api/v1/admin/users/{member.id}/password",
        json={"new_password": "a brand new passphrase"},
        headers=csrf,
    )
    assert r.status_code == 204, r.text
    client.cookies.clear()
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": member.email, "password": PASSWORD, "organization": world.tenant.slug},
        )
    ).status_code == 401
    await login(client, world, member.email, "a brand new passphrase")
    assert (await client.get("/api/v1/users/me")).status_code == 200
    # The admin signs the member out everywhere: session cookies and API tokens stop working.
    r = await client.post(f"/api/v1/admin/users/{member.id}/sessions/revoke", headers=world.headers)
    assert r.status_code == 204
    assert (await client.get("/api/v1/users/me")).status_code == 401
    assert (await client.get("/api/v1/users/me", headers=auth(member_token))).status_code == 401


async def test_deactivation_ends_sessions(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await login(client, world, member.email)
    cookies = dict(client.cookies)
    r = await client.patch(f"/api/v1/users/{member.id}", json={"is_active": False}, headers=world.headers)
    assert r.status_code == 200
    client.cookies.clear()
    client.cookies.update(cookies)
    assert (await client.get("/api/v1/users/me")).status_code == 401
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 401


async def test_logins_and_domain_events_are_audited(client: AsyncClient) -> None:
    world = await make_world()
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": world.owner.email, "password": "wrong password!", "organization": world.tenant.slug},
    )
    assert bad.status_code == 401
    await login(client, world, world.owner.email)
    logins = await audit(world, "auth.login")
    assert [e.outcome for e in logins] == ["denied", "ok"]
    assert logins[0].detail["reason"] == "invalid credentials" and "password" not in json.dumps(
        logins[0].detail
    )

    task = await create_task(client, world, title="Audited")
    (event,) = await events_for(task["id"], "task.created")
    await record_event(event)
    await record_event(event)  # consumers are at-least-once: the second write is a no-op
    entries = await audit(world, "task.created")
    assert len(entries) == 1 and entries[0].target == f"task:{task['id']}"
    assert entries[0].actor_id == world.owner.id

    log = await client.get(
        "/api/v1/audit-log", params={"action": "auth.", "outcome": "denied"}, headers=world.headers
    )
    assert [e["action"] for e in log.json()] == ["auth.login"]


async def test_read_only_tokens_cannot_administer(client: AsyncClient) -> None:
    world = await make_world()
    admin = await make_user(world.tenant, OrgRole.ADMIN)
    read_only = auth(await token_for(admin, (Scope.READ,)))
    r = await client.patch("/api/v1/admin/settings", json={"audit_retention_days": 60}, headers=read_only)
    assert r.status_code == 403
