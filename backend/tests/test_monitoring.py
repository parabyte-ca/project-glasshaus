"""System status: checks, the Admin page, alerts, the worker watchdog and Prometheus gauges."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest
from httpx import AsyncClient

from glasshaus import mail, monitoring
from glasshaus.config import get_settings
from glasshaus.core.rbac import OrgRole
from glasshaus.redis_client import get_redis
from tests.factories import auth, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


@pytest.fixture
async def clean() -> None:
    await get_redis().delete(
        monitoring.SNAPSHOT_KEY, monitoring.WATCHDOG_KEY, monitoring.HEARTBEAT_KEY, monitoring.ARQ_QUEUE
    )


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EmailMessage]]:
    monkeypatch.setattr(get_settings(), "smtp_host", "memory")
    mail.OUTBOX.clear()
    yield mail.OUTBOX
    mail.OUTBOX.clear()


async def _beat(age: timedelta = timedelta(0)) -> None:
    await get_redis().set(monitoring.HEARTBEAT_KEY, (datetime.now(UTC) - age).isoformat(), ex=180)


async def test_status_page_for_admins(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean: None
) -> None:
    monkeypatch.setattr(get_settings(), "backup_status_dir", str(tmp_path))
    world = await make_world()
    member = await make_user(world.tenant, OrgRole.MEMBER)
    await _beat()

    r = await client.get("/api/v1/admin/status", headers=world.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    checks = {c["key"]: c for c in body["checks"]}
    assert list(checks) == [
        "database",
        "redis",
        "worker",
        "queue",
        "events",
        "integrations",
        "backups",
        "disk",
        "updates",
    ]
    assert checks["database"]["state"] == "ok" and checks["database"]["metrics"]["size_bytes"] > 0
    assert checks["redis"]["state"] == "ok" and checks["worker"]["state"] == "ok"
    # An empty backup folder: no backup yet is critical, and drives the overall state.
    assert checks["backups"]["state"] == "critical" and body["overall"] == "critical"
    assert checks["disk"]["metrics"]["free_bytes"] > 0

    assert (
        await client.get("/api/v1/admin/status", headers=auth(await token_for(member)))
    ).status_code == 403
    monkeypatch.setattr(get_settings(), "multi_tenant", True)
    assert (await client.get("/api/v1/admin/status", headers=world.headers)).status_code == 404


async def test_checks_flag_problems(monkeypatch: pytest.MonkeyPatch, clean: None) -> None:
    now = datetime.now(UTC)
    assert (await monitoring._worker(now)).state == "critical"  # never checked in
    await _beat(timedelta(seconds=150))
    worker = await monitoring._worker(now)
    assert worker.state == "warning" and worker.metrics["heartbeat_age_seconds"] > 140

    await get_redis().zadd(monitoring.ARQ_QUEUE, {f"job{i}": i for i in range(150)})
    queue = await monitoring._queue()
    assert queue.state == "warning" and queue.message == "150 jobs waiting."

    monkeypatch.setattr(get_settings(), "backup_status_dir", "")
    status = await monitoring.collect(now)
    assert "backups" not in {c.key for c in status.checks} and "disk" not in {c.key for c in status.checks}
    assert monitoring.RANK[status.overall] >= monitoring.RANK["warning"]


async def test_watch_alerts_once_per_window(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, outbox: list[EmailMessage], clean: None
) -> None:
    monkeypatch.setattr(get_settings(), "backup_status_dir", "")
    world = await make_world()
    member = await make_user(world.tenant, OrgRole.MEMBER)
    await get_redis().zadd(monitoring.ARQ_QUEUE, {f"job{i}": i for i in range(150)})
    await _beat()

    assert await monitoring.watch() >= 1
    assert await monitoring.watch() == 0  # same problem, same window: nothing new
    notes = (await client.get("/api/v1/notifications", headers=world.headers)).json()["items"]
    mine = [n for n in notes if n["title"].startswith("Job queue:")]
    assert len(mine) == 1 and mine[0]["link"] == "/admin?tab=status"
    member_notes = (await client.get("/api/v1/notifications", headers=auth(await token_for(member)))).json()
    assert not [n for n in member_notes["items"] if n["title"].startswith("Job queue:")]
    sent = [m for m in outbox if m["To"] == world.owner.email]
    assert sent and sent[0]["Subject"] == "Glasshaus needs attention"
    assert "Job queue: 150 jobs waiting." in sent[0].get_content()

    # The snapshot feeds /metrics.
    metrics = (await client.get("/metrics")).text
    assert 'glasshaus_check_state{check="queue"} 2' in metrics
    assert "glasshaus_queue_jobs 150.0" in metrics and "glasshaus_build_info{" in metrics


async def test_api_watches_the_worker(client: AsyncClient, clean: None) -> None:
    world = await make_world()
    assert await monitoring.watch_worker() >= 1  # no heartbeat: the worker is down
    assert await monitoring.watch_worker() == 0  # another API process within the interval
    notes = (await client.get("/api/v1/notifications", headers=world.headers)).json()["items"]
    assert [n for n in notes if n["title"].startswith("Background worker:")]

    await get_redis().delete(monitoring.WATCHDOG_KEY)
    await _beat()
    assert await monitoring.watch_worker() == 0


async def test_metrics_token(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("scrape-me"))
    assert (await client.get("/metrics")).status_code == 401
    bad = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    good = await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert good.status_code == 200 and "glasshaus_build_info" in good.text
