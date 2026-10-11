"""Backup health: status from the backup folder, and daily notifications while something is wrong."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus import backups
from glasshaus.config import get_settings
from glasshaus.core.rbac import OrgRole
from tests.factories import auth, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def dump(folder: Path, name: str, age: timedelta, size: int = 2048, *, encrypted: bool = False) -> None:
    path = folder / f"glasshaus-{name}.dump{'.age' if encrypted else ''}"
    path.write_bytes(b"x" * size)
    if encrypted:
        (folder / f"{path.name}.sha256").write_text(f"abc  {path.name}\n")
    stamp = (datetime.now(UTC) - age).timestamp()
    os.utime(path, (stamp, stamp))


def drill(folder: Path, **fields: Any) -> None:
    body = {
        "finished_at": datetime.now(UTC).isoformat(),
        "ok": True,
        "dump": "glasshaus-a.dump",
        "dump_bytes": 2048,
        "seconds": 3,
        "tables": 60,
        "revision": "fe53990766f9",
        "live_revision": "fe53990766f9",
        "rows": {"users": 2, "projects": 1, "tasks": 5},
        "error": "",
        **fields,
    }
    (folder / "drill-status.json").write_text(json.dumps(body))


def test_status_reports_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "backup_status_dir", "")
    assert backups.status().available is False

    monkeypatch.setattr(settings, "backup_status_dir", str(tmp_path))
    assert [p.code for p in backups.status().problems] == ["no_backup"]

    dump(tmp_path, "a", timedelta(hours=3), encrypted=True)
    dump(tmp_path, "b", timedelta(hours=27), size=1024)
    drill(tmp_path)
    found = backups.status()
    assert found.available and found.problems == [] and found.count == 2 and found.total_bytes == 3072
    assert [f.name for f in found.latest] == ["glasshaus-a.dump.age", "glasshaus-b.dump"]
    assert [(f.encrypted, f.checksum) for f in found.latest] == [(True, True), (False, False)]
    assert found.drill is not None and found.drill.rows["tasks"] == 5

    drill(tmp_path, ok=False, error="pg_restore failed: bad header")
    assert [p.message for p in backups.status().problems] == [
        "The last restore drill failed: pg_restore failed: bad header"
    ]
    drill(tmp_path, finished_at=(datetime.now(UTC) - timedelta(days=20)).isoformat())
    later = backups.status(datetime.now(UTC) + timedelta(days=2))
    assert [p.code for p in later.problems] == ["backup_stale", "drill_overdue"]
    (tmp_path / "drill-status.json").write_text("{not json")
    assert "drill_unreadable" in [p.code for p in backups.status().problems]


async def test_admin_page_and_daily_notification(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "backup_status_dir", str(tmp_path))
    dump(tmp_path, "old", timedelta(days=15))
    world = await make_world()
    member = await make_user(world.tenant, OrgRole.MEMBER)
    r = await client.get("/api/v1/admin/backups", headers=world.headers)
    assert r.status_code == 200 and [p["code"] for p in r.json()["problems"]] == [
        "backup_stale",
        "drill_missing",
    ]
    assert (
        await client.get("/api/v1/admin/backups", headers=auth(await token_for(member)))
    ).status_code == 403

    assert await backups.watch() >= 2
    await backups.watch()  # the same day again: no repeats
    notes = (await client.get("/api/v1/notifications", headers=world.headers)).json()["items"]
    mine = [n for n in notes if n["kind"] == "system"]
    assert len(mine) == 2 and all(n["link"] == "/admin?tab=backups" for n in mine)
    assert mine[0]["title"].startswith("Backups: ")
    member_notes = (await client.get("/api/v1/notifications", headers=auth(await token_for(member)))).json()
    assert [n for n in member_notes["items"] if n["kind"] == "system"] == []

    monkeypatch.setattr(get_settings(), "multi_tenant", True)
    assert (await client.get("/api/v1/admin/backups", headers=world.headers)).status_code == 404
    assert await backups.watch() == 0
