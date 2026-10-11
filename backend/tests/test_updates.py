import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from glasshaus import updates
from glasshaus.config import get_settings
from glasshaus.core.errors import InvalidInput, PermissionDenied
from glasshaus.core.rbac import OrgRole
from glasshaus.db import unit_of_work
from glasshaus.redis_client import get_redis
from glasshaus.updates import Release, UpgradeRequest
from tests.factories import actor_for, auth, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def _release(version: str) -> Release:
    return Release(
        version=version,
        name=f"v{version}",
        notes="### Added\n- Things",
        url=f"https://github.com/o/r/releases/tag/v{version}",
        published_at=datetime(2026, 10, 10, tzinfo=UTC),
    )


def _helper(folder: Path, seen: datetime | None = None) -> None:
    seen = seen or datetime.now(UTC)
    (folder / "agent.json").write_text(json.dumps({"last_seen": seen.isoformat().replace("+00:00", "Z")}))


@pytest.fixture
async def fresh_cache() -> None:
    await get_redis().delete(updates.LATEST_KEY)


def test_versions_and_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    assert updates.newer("0.26.0", "0.25.9") and updates.newer("1.0.0", "0.99.99")
    assert not updates.newer("0.25.0", "0.25.0") and not updates.newer("garbage", "0.1.0")
    assert updates._repo() == "parabyte-ca/project-glasshaus"
    monkeypatch.setattr(get_settings(), "source_url", "https://git.example.com/me/fork")
    assert updates._repo() is None


async def test_daily_check_notifies_admins_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, fresh_cache: None
) -> None:
    world = await make_world()
    member = await make_user(world.tenant, OrgRole.MEMBER)

    async def latest() -> Release:
        return _release("99.0.0")

    monkeypatch.setattr(updates, "fetch_latest", latest)
    assert await updates.daily_check() == 1
    await updates.daily_check()  # the same release again: no second notification
    notes = (await client.get("/api/v1/notifications", headers=world.headers)).json()["items"]
    mine = [n for n in notes if n["title"] == "Glasshaus 99.0.0 is available"]
    assert len(mine) == 1 and mine[0]["link"] == "/admin?tab=updates"
    member_notes = (await client.get("/api/v1/notifications", headers=auth(await token_for(member)))).json()
    assert not [n for n in member_notes["items"] if "is available" in n["title"]]

    r = await client.get("/api/v1/admin/updates", headers=world.headers)
    body = r.json()
    assert r.status_code == 200 and body["update_available"] is True and body["latest"]["version"] == "99.0.0"
    assert body["helper"] == {"configured": False, "connected": False, "last_seen": None}
    assert body["can_upgrade"] is False  # no helper
    assert (
        await client.get("/api/v1/admin/updates", headers=auth(await token_for(member)))
    ).status_code == 403

    # A failed check keeps the last known release and says why.
    async def broken() -> Release:
        raise InvalidInput("no releases published yet")

    monkeypatch.setattr(updates, "fetch_latest", broken)
    entry = await updates.check()
    assert entry["release"]["version"] == "99.0.0" and entry["error"] == "no releases published yet"

    monkeypatch.setattr(get_settings(), "update_check", False)
    assert await updates.daily_check() == 0
    monkeypatch.setattr(get_settings(), "multi_tenant", True)
    assert (await client.get("/api/v1/admin/updates", headers=world.headers)).status_code == 404


async def test_owner_requests_an_upgrade_for_the_host_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_cache: None
) -> None:
    monkeypatch.setattr(get_settings(), "upgrade_dir", str(tmp_path))
    await get_redis().set(
        updates.LATEST_KEY,
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "release": _release("99.0.0").model_dump(mode="json"),
            }
        ),
    )
    world = await make_world()
    admin = await make_user(world.tenant, OrgRole.ADMIN)
    want = UpgradeRequest(version="99.0.0")

    async with unit_of_work(actor_for(world.owner)) as ctx:
        with pytest.raises(InvalidInput, match="helper"):
            await updates.request_upgrade(ctx, want)
    _helper(tmp_path, datetime.now(UTC) - timedelta(minutes=10))  # stale: cron isn't running
    async with unit_of_work(actor_for(world.owner)) as ctx:
        status = await updates.get_status(ctx)
        assert status.helper.configured and not status.helper.connected and not status.can_upgrade
    _helper(tmp_path)
    async with unit_of_work(actor_for(admin)) as ctx:
        assert (await updates.get_status(ctx)).can_upgrade is False  # admins see it, owners act
        with pytest.raises(PermissionDenied):
            await updates.request_upgrade(ctx, want)
    async with unit_of_work(actor_for(world.owner)) as ctx:
        with pytest.raises(InvalidInput, match="latest release"):
            await updates.request_upgrade(ctx, UpgradeRequest(version="98.0.0"))
        status = await updates.request_upgrade(ctx, want)
    assert status.upgrade is not None and status.upgrade.state == "requested"
    request = json.loads((tmp_path / "request.json").read_text())
    assert request["version"] == "99.0.0" and request["requested_by"] == world.owner.email
    async with unit_of_work(actor_for(world.owner)) as ctx:
        with pytest.raises(InvalidInput, match="already under way"):
            await updates.request_upgrade(ctx, want)

    # The helper takes the request and reports back.
    (tmp_path / "request.json").unlink()
    (tmp_path / "status.json").write_text(
        json.dumps(
            {"id": request["id"], "state": "running", "from_version": "0.26.0", "to_version": "99.0.0"}
        )
    )
    (tmp_path / "upgrade.log").write_text("==> Backing up database\n")
    async with unit_of_work(actor_for(world.owner)) as ctx:
        status = await updates.get_status(ctx)
    assert status.upgrade is not None and status.upgrade.state == "running" and not status.can_upgrade
    assert status.log == "==> Backing up database\n"
    async with unit_of_work(actor_for(admin)) as ctx:
        assert (await updates.get_status(ctx)).log is None  # the log is for owners

    token = replace(actor_for(world.owner), method="token", scopes=frozenset({"admin"}))
    (tmp_path / "status.json").write_text(json.dumps({"id": request["id"], "state": "succeeded"}))
    async with unit_of_work(token) as ctx:
        with pytest.raises(PermissionDenied, match="web app"):
            await updates.request_upgrade(ctx, want)
