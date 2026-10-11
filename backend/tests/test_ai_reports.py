"""AI answers from reports (fake provider) and the report tools for MCP clients."""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from glasshaus.ai import providers
from tests.factories import auth, create_task, make_user, make_world, token_for
from tests.test_ai import INJECTED, enable, fake  # noqa: F401 - fixture
from tests.test_governance import audit
from tests.test_mcp_tools import call, call_error, connect, token_actor

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


def plan(**overrides: Any) -> dict[str, Any]:
    return {
        "saved_report": None,
        "source": "tasks",
        "group_by": ["priority"],
        "measures": ["count", "overdue"],
        "project_keys": [],
        "people": [],
        "status_categories": [],
        "priorities": [],
        "date_field": None,
        "date_preset": None,
        "date_from": None,
        "date_to": None,
        "chart": "bar",
        "sort_by": "overdue",
        "descending": True,
        "explanation": "Tasks and overdue tasks by priority",
        **overrides,
    }


async def test_reports_feature_is_its_own_switch(client: AsyncClient, fake: providers.FakeProvider) -> None:  # noqa: F811
    world = await make_world()
    await enable(client, world)  # the default features do not include reports
    r = await client.post("/api/v1/ai/reports", json={"question": "how many tasks?"}, headers=world.headers)
    assert r.status_code == 503 and "'reports' is turned off" in r.json()["detail"]


async def test_question_becomes_a_report_run_with_your_access(
    client: AsyncClient,
    fake: providers.FakeProvider,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await make_world()
    await enable(client, world, ai_features=["reports"])
    late = (date.today() - timedelta(days=2)).isoformat()
    await create_task(client, world, title=INJECTED, priority="high", due_date=late)
    await create_task(client, world, title="Fine", priority="high")
    await create_task(client, world, title="Low one", priority="low")
    monkeypatch.setitem(
        providers.FAKE_RESPONSES,
        "ReportPlan",
        plan(
            project_keys=[world.project.key.lower(), "ZZZ"], people=["Nobody"], group_by=["priority", "bogus"]
        ),
    )
    monkeypatch.setitem(providers.FAKE_RESPONSES, "ReportAnswer", {"answer": "High has 1 overdue task."})
    r = await client.post(
        "/api/v1/ai/reports", json={"question": "Which priority is most overdue?"}, headers=world.headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "High has 1 overdue task." and body["saved_report_id"] is None
    definition = body["definition"]
    assert definition["group_by"] == ["priority"]  # unknown groupings dropped
    assert definition["filters"]["project_ids"] == [str(world.project.id)]  # unknown keys dropped
    assert definition["filters"]["people"] == []  # unknown names dropped
    rows = {tuple(row["labels"]): row["values"] for row in body["result"]["rows"]}
    assert rows == {("High",): [2, 1], ("Low",): [1, 0]}

    planning, answering = fake.calls[-2], fake.calls[-1]
    assert planning["output"] == "ReportPlan" and answering["output"] == "ReportAnswer"
    assert world.project.key in planning["prompt"] and "Which priority" in planning["prompt"]
    assert INJECTED not in planning["prompt"] and INJECTED not in answering["prompt"]  # no task titles sent
    assert '"High"' in answering["prompt"]
    assert [e.outcome for e in await audit(world, "ai.reports")] == ["ok", "ok"]

    outsider = await make_user(world.tenant)
    r = await client.post(
        "/api/v1/ai/reports", json={"question": "Which priority?"}, headers=auth(await token_for(outsider))
    )
    assert r.json()["result"]["totals"] == [0, 0]  # the plan named the project; the run still checks access


async def test_saved_reports_are_used_by_name_or_id(
    client: AsyncClient,
    fake: providers.FakeProvider,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await make_world()
    await enable(client, world, ai_features=["reports"])
    await create_task(client, world)
    saved = (
        await client.post(
            "/api/v1/reports",
            json={"name": "Open work", "description": "Open tasks", "definition": {"measures": ["open"]}},
            headers=world.headers,
        )
    ).json()
    monkeypatch.setitem(providers.FAKE_RESPONSES, "ReportPlan", plan(saved_report=" open WORK "))
    body = (await client.post("/api/v1/ai/reports", json={"question": "open?"}, headers=world.headers)).json()
    assert body["saved_report_id"] == saved["id"] and body["saved_report_name"] == "Open work"
    assert body["result"]["totals"] == [1]
    assert "Open work" in fake.calls[-2]["prompt"]

    calls = len(fake.calls)
    body = (
        await client.post(
            "/api/v1/ai/reports",
            json={"question": "summarise", "report_id": saved["id"]},
            headers=world.headers,
        )
    ).json()
    assert body["saved_report_id"] == saved["id"] and body["explanation"] == "Open tasks"
    assert len(fake.calls) == calls + 1  # no planning call when the report is given
    r = await client.post(
        "/api/v1/ai/reports",
        json={"question": "x?", "report_id": "00000000-0000-0000-0000-000000000000"},
        headers=world.headers,
    )
    assert r.status_code == 404


async def test_mcp_report_tools(client: AsyncClient, fake: providers.FakeProvider) -> None:  # noqa: F811
    world = await make_world()
    await create_task(client, world, priority="high")
    async with connect(token_actor(world, {"read", "tasks:write"})) as mcp:
        assert (await call(mcp, "list_reports"))["reports"] == []
        result = await call(mcp, "run_report", definition={"group_by": ["priority"], "measures": ["count"]})
        assert [row["labels"] for row in result["rows"]] == [["High"]]
        assert "invalid report definition" in await call_error(
            mcp, "run_report", definition={"source": "time", "measures": ["count"]}
        )
        assert "either report_id or definition" in await call_error(mcp, "run_report")
        saved = await call(
            mcp, "manage_reports", action="create", name="By priority", definition={"group_by": ["priority"]}
        )
        ran = await call(
            mcp, "run_report", report_id=saved["id"], date_preset="last_7_days", projects=[world.project.key]
        )
        assert ran["totals"] == [1] and ran["date_to"] == date.today().isoformat()
        preview = await call(mcp, "manage_reports", action="delete", report_id=saved["id"])
        assert preview == {"preview": True, "would_delete": "By priority"}
        await call(mcp, "manage_reports", action="delete", report_id=saved["id"], confirm=True)
        assert (await call(mcp, "list_reports"))["reports"] == []
        assert "turned off" in await call_error(mcp, "ai_ask_reports", question="how many?")
    async with connect(token_actor(world, {"read"})) as mcp:
        assert "scope" in await call_error(
            mcp, "manage_reports", action="create", name="x", definition={"measures": ["count"]}
        )
