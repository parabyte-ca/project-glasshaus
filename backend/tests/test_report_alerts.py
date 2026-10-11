"""Report alerts: notify on crossing a threshold (and on recovery), with the owner's access."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus import mail
from glasshaus.config import get_settings
from glasshaus.reports.alerts import check_due
from tests.factories import auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

DAILY = {"frequency": "daily", "hour": 7, "minute": 30, "timezone": "UTC"}


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EmailMessage]]:
    monkeypatch.setattr(get_settings(), "smtp_host", "memory")
    mail.OUTBOX.clear()
    yield mail.OUTBOX
    mail.OUTBOX.clear()


async def notifications(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    r = await client.get("/api/v1/notifications", headers=headers)
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return [n for n in items if n["kind"] == "report_alert"]


async def test_alert_fires_once_and_clears(client: AsyncClient, outbox: list[EmailMessage]) -> None:
    world = await make_world()
    first = await create_task(client, world)
    r = await client.post(
        "/api/v1/reports",
        json={"name": "Open work", "shared": True, "definition": {"measures": ["count", "open"]}},
        headers=world.headers,
    )
    report = r.json()
    url = f"/api/v1/reports/{report['id']}/alert"
    assert (await client.get(url, headers=world.headers)).json() is None
    bad = {"measure": "hours", "direction": "above", "threshold": 2, "schedule": DAILY}
    r = await client.put(url, json=bad, headers=world.headers)
    assert r.status_code == 422 and "no 'hours' measure" in r.json()["detail"]
    body = {"measure": "open", "direction": "above", "threshold": 2, "schedule": DAILY, "email": True}
    alert = (await client.put(url, json=body, headers=world.headers)).json()
    assert alert["state"] == "unknown" and alert["measure_label"] == "Open"

    # 1 open: fine, and the first "ok" says nothing.
    checked = (await client.post(f"{url}/check", headers=world.headers)).json()
    assert checked["state"] == "ok" and checked["last_value"] == 1
    assert await notifications(client, world.headers) == [] and outbox == []

    # 3 open: over the threshold -> one notification (with a link) and one email.
    await create_task(client, world)
    await create_task(client, world)
    checked = (await client.post(f"{url}/check", headers=world.headers)).json()
    assert checked["state"] == "triggered" and checked["last_value"] == 3
    [note] = await notifications(client, world.headers)
    assert note["title"] == "Open work: Open is 3, above 2" and note["link"] == f"/reports/{report['id']}"
    assert [m["Subject"] for m in outbox] == ["Open work: Open is 3, above 2"]
    # Still over: nothing new.
    await client.post(f"{url}/check", headers=world.headers)
    assert len(await notifications(client, world.headers)) == 1

    # Back under (scheduled check): a "back to" notification.
    await client.delete(f"/api/v1/tasks/{first['id']}", headers=world.headers)
    due = datetime.fromisoformat(alert["next_run_at"])
    assert await check_due(due + timedelta(seconds=5)) == {"cleared": 1}
    titles = [n["title"] for n in await notifications(client, world.headers)]
    assert titles[0] == "Open work: Open is back to 2 (alert: above 2)"
    after = (await client.get(url, headers=world.headers)).json()
    assert after["state"] == "ok" and datetime.fromisoformat(after["next_run_at"]) == due + timedelta(days=1)
    assert [
        a["report_id"] for a in (await client.get("/api/v1/reports/alerts", headers=world.headers)).json()
    ] == [report["id"]]

    # The report loses the measure: the alert stays and says why it cannot check.
    await client.patch(
        f"/api/v1/reports/{report['id']}", json={"definition": {"measures": ["count"]}}, headers=world.headers
    )
    checked = (await client.post(f"{url}/check", headers=world.headers)).json()
    assert checked["last_error"] == "the report no longer has the measure 'Open'" and checked["state"] == "ok"

    assert (await client.delete(url, headers=world.headers)).status_code == 204
    assert (await client.delete(url, headers=world.headers)).status_code == 404


async def test_alerts_use_the_owners_access_and_end_with_it(client: AsyncClient) -> None:
    world = await make_world()
    for _ in range(3):
        await create_task(client, world)
    r = await client.post(
        "/api/v1/reports",
        json={"name": "Everything", "shared": True, "definition": {"measures": ["count"]}},
        headers=world.headers,
    )
    report = r.json()
    url = f"/api/v1/reports/{report['id']}/alert"
    outsider = await make_user(world.tenant)
    headers = auth(await token_for(outsider))
    body = {"measure": "count", "direction": "above", "threshold": 0, "schedule": DAILY}
    assert (await client.put(url, json=body, headers=headers)).status_code == 200
    checked = (await client.post(f"{url}/check", headers=headers)).json()
    assert checked["last_value"] == 0 and checked["state"] == "ok"  # cannot see the project's tasks

    await client.patch(f"/api/v1/reports/{report['id']}", json={"shared": False}, headers=world.headers)
    due = datetime.fromisoformat(checked["next_run_at"])
    assert await check_due(due + timedelta(seconds=5)) == {"dropped": 1}
    assert (await client.get("/api/v1/reports/alerts", headers=headers)).json() == []

    stranger = await make_world()
    assert (await client.put(url, json=body, headers=stranger.headers)).status_code == 404
