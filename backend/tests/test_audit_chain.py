"""The audit log is append-only and hash-chained: tampering shows up, and only retention removes entries."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from glasshaus.audit import service as audit
from glasshaus.audit.models import AuditEntry
from glasshaus.core.context import Actor
from glasshaus.db import apply_tenant, system_session
from glasshaus.governance.service import apply_retention
from tests.factories import (
    PASSWORD,
    World,
    auth,
    backdate_audit,
    events_for,
    make_user,
    make_world,
    owner_session,
    token_for,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def write(world: World, *actions: str) -> None:
    for action in actions:
        await audit.record(Actor.system(world.tenant.id), action, outcome="ok", detail={"n": action})


async def entries(world: World) -> list[AuditEntry]:
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        rows = await session.scalars(
            select(AuditEntry).where(AuditEntry.tenant_id == world.tenant.id).order_by(AuditEntry.seq)
        )
        return list(rows.all())


async def verify(client: AsyncClient, world: World) -> dict:  # type: ignore[type-arg]
    r = await client.post("/api/v1/audit-log/verify", headers=world.headers)
    assert r.status_code == 200, r.text
    result: dict = r.json()  # type: ignore[type-arg]
    return result


async def test_entries_are_numbered_and_chained(client: AsyncClient) -> None:
    world = await make_world()
    await write(world, "a", "b", "c")
    rows = await entries(world)
    assert [r.seq for r in rows] == list(range(1, len(rows) + 1))
    assert all(r.prev_hash == p.hash for p, r in pairwise(rows))
    check = await verify(client, world)
    assert check["ok"] and check["problems"] == [] and check["head"] == rows[-1].hash.hex()
    # Verifying is itself recorded, and members cannot verify.
    assert (await entries(world))[-1].action == "audit.verified"
    member = auth(await token_for(await make_user(world.tenant)))
    assert (await client.post("/api/v1/audit-log/verify", headers=member)).status_code == 403


async def test_the_application_cannot_change_or_remove_entries() -> None:
    world = await make_world()
    await write(world, "keep")
    for stmt in (
        update(AuditEntry).where(AuditEntry.tenant_id == world.tenant.id).values(action="rewritten"),
        delete(AuditEntry).where(AuditEntry.tenant_id == world.tenant.id),
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with system_session() as session:
                await session.execute(stmt)
    # Purging recent entries is refused by the database as well.
    with pytest.raises(DBAPIError, match="kept for 365 days"):
        async with system_session() as session:
            await session.scalar(select(func.glasshaus_audit_purge(world.tenant.id, datetime.now(UTC))))
    assert [r.action for r in await entries(world)][-1] == "keep"


async def test_tampering_by_the_database_owner_is_detected(client: AsyncClient) -> None:
    world = await make_world()
    await write(world, "one", "two", "three", "four")
    rows = await entries(world)
    by_action = {r.action: r for r in rows}
    async with owner_session() as session:
        await session.execute(
            text('UPDATE audit_log SET detail = \'{"n": "edited"}\' WHERE id = :id'),
            {"id": by_action["two"].id},
        )
        await session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": by_action["three"].id})
    problems = {p["seq"]: p["problem"] for p in (await verify(client, world))["problems"]}
    assert problems[by_action["two"].seq] == "changed after it was recorded"
    assert "missing" in problems[by_action["four"].seq]


async def test_retention_purges_old_entries_and_records_it(client: AsyncClient) -> None:
    world = await make_world()
    await client.patch("/api/v1/admin/settings", json={"audit_retention_days": 30}, headers=world.headers)
    await write(world, "ancient")
    await backdate_audit(world, "ancient", datetime.now(UTC) - timedelta(days=45))
    # Everything older than "ancient" too (the organization's setup), so the purge is a clean prefix.
    async with owner_session() as session:
        await session.execute(
            text("UPDATE audit_log SET created_at = now() - interval '46 days' WHERE tenant_id = :t AND seq < "
                 "(SELECT seq FROM audit_log WHERE tenant_id = :t AND action = 'ancient')"),
            {"t": world.tenant.id},
        )  # fmt: skip
    await write(world, "recent")
    await apply_retention()
    actions = [r.action for r in await entries(world)]
    assert "ancient" not in actions and "recent" in actions
    purge = next(r for r in await entries(world) if r.action == "audit.purged")
    assert purge.detail["count"] >= 1
    check = await verify(client, world)
    assert check["ok"], check["problems"]
    assert check["starts_after_purge"] is True
    # Changing retention is recorded with the previous value.
    await client.patch("/api/v1/admin/settings", json={"audit_retention_days": 90}, headers=world.headers)
    changed = (await events_for(str(world.tenant.id), "org.settings_updated"))[-1]["data"]
    assert changed == {"changes": {"audit_retention_days": 90}, "previous": {"audit_retention_days": 30}}


async def test_audit_retention_has_a_floor(client: AsyncClient) -> None:
    world = await make_world()
    bad = await client.patch(
        "/api/v1/admin/settings", json={"audit_retention_days": 7}, headers=world.headers
    )
    assert bad.status_code == 422
    ok = await client.patch("/api/v1/admin/settings", json={"audit_retention_days": 0}, headers=world.headers)
    assert ok.status_code == 200


async def test_sign_out_is_audited(client: AsyncClient) -> None:
    world = await make_world()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": world.owner.email, "password": PASSWORD, "organization": world.tenant.slug},
    )
    assert r.status_code == 200, r.text
    r = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies["gh_csrf"]})
    assert r.status_code in (200, 204), r.text
    logout = [e for e in await entries(world) if e.action == "auth.logout"]
    assert len(logout) == 1 and logout[0].actor_id == world.owner.id
