"""Onboarding: per-person tour/checklist/tip state, and milestones read from the person's own work."""

import pytest
from httpx import AsyncClient

from glasshaus.core.rbac import OrgRole
from tests.factories import add_member, auth, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]
URL = "/api/v1/users/me/onboarding"


async def test_state_and_milestones(client: AsyncClient) -> None:
    world = await make_world()
    member = await make_user(world.tenant, OrgRole.MEMBER)
    headers = auth(await token_for(member))

    fresh = (await client.get(URL, headers=headers)).json()
    assert fresh == {
        "tour": None,
        "tour_finished_at": None,
        "checklist": "open",
        "dismissed_tips": [],
        "milestones": {
            "created_work": False,
            "added_collaborator": False,
            "set_due_date": False,
            "toured": False,
        },
    }

    # Milestones tick themselves from real work.
    await add_member(client, world, member, "editor")
    task = {"project_id": str(world.project.id), "title": "First", "assignee_id": str(world.owner.id)}
    assert (await client.post("/api/v1/tasks", json=task, headers=headers)).status_code == 201
    m = (await client.get(URL, headers=headers)).json()["milestones"]
    assert m == {"created_work": True, "added_collaborator": True, "set_due_date": False, "toured": False}
    dated = {**task, "title": "Second", "due_date": "2026-12-01"}
    assert (await client.post("/api/v1/tasks", json=dated, headers=headers)).status_code == 201
    assert (await client.get(URL, headers=headers)).json()["milestones"]["set_due_date"] is True

    # Explicit state: tour, checklist, tips (deduplicated), then start over.
    r = await client.patch(URL, json={"tour": "completed", "checklist": "minimized"}, headers=headers)
    body = r.json()
    assert r.status_code == 200 and body["tour"] == "completed" and body["tour_finished_at"]
    assert body["checklist"] == "minimized" and body["milestones"]["toured"] is True
    for tip in ("timeline", "automations", "timeline"):
        r = await client.patch(URL, json={"dismiss_tip": tip}, headers=headers)
    assert r.json()["dismissed_tips"] == ["automations", "timeline"]
    assert (await client.patch(URL, json={"dismiss_tip": "<script>"}, headers=headers)).status_code == 422
    assert (await client.patch(URL, json={"tour": "maybe"}, headers=headers)).status_code == 422
    reset = (await client.patch(URL, json={"reset": True}, headers=headers)).json()
    assert reset["tour"] is None and reset["checklist"] == "open" and reset["dismissed_tips"] == []

    # State is per person: the owner's is untouched.
    owner = (await client.get(URL, headers=world.headers)).json()
    assert owner["tour"] is None and owner["dismissed_tips"] == []
