import uuid

import pytest

from glasshaus.api.ws import origin_allowed
from glasshaus.core.context import Actor
from glasshaus.core.rbac import OrgRole
from glasshaus.realtime import VisibilityCache, to_client

TENANT, USER, PROJECT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
ACTOR = Actor(tenant_id=TENANT, user_id=USER, org_role=OrgRole.MEMBER, method="session")


def make_cache(visible: set[uuid.UUID]) -> tuple[VisibilityCache, list[uuid.UUID]]:
    calls: list[uuid.UUID] = []

    async def check(pid: uuid.UUID) -> bool:
        calls.append(pid)
        return pid in visible

    return VisibilityCache(check), calls


def event(
    type_: str = "task.updated", project: uuid.UUID | None = PROJECT, actor: uuid.UUID | None = None
) -> dict:  # type: ignore[type-arg]
    return {
        "id": "e1",
        "type": type_,
        "aggregate_type": "task",
        "aggregate_id": "t1",
        "project_id": str(project) if project else None,
        "actor": {"user_id": str(actor) if actor else None},
        "data": {"task": {"title": "secret"}},
    }


async def test_visible_events_carry_ids_only() -> None:
    cache, _ = make_cache({PROJECT})
    out = await to_client(event(), ACTOR, cache)
    assert out == {
        "id": "e1",
        "type": "task.updated",
        "aggregate_type": "task",
        "aggregate_id": "t1",
        "project_id": str(PROJECT),
    }


async def test_invisible_and_foreign_events_are_dropped() -> None:
    cache, _ = make_cache(set())
    assert await to_client(event(), ACTOR, cache) is None
    assert await to_client(event(project=None, actor=uuid.uuid4()), ACTOR, cache) is None
    assert await to_client(event(project=None, actor=USER), ACTOR, cache) is not None


async def test_signals_target_users_and_membership_changes_reset_cache() -> None:
    cache, calls = make_cache({PROJECT})
    sig = {"type": "notification.created", "signal": True, "user_ids": [str(USER)]}
    assert await to_client(sig, ACTOR, cache) == {"type": "notification.created"}
    assert await to_client({**sig, "user_ids": [str(uuid.uuid4())]}, ACTOR, cache) is None
    await to_client(event(), ACTOR, cache)
    await to_client(event(), ACTOR, cache)
    assert len(calls) == 1
    await to_client(event("project.member_removed"), ACTOR, cache)
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("origin", "host", "ok"),
    [
        ("http://localhost:8470", "localhost:8471", True),  # configured public URL
        ("https://evil.example", "glasshaus.lan", False),
        ("https://glasshaus.lan", "glasshaus.lan", True),  # same origin as the request
        (None, "glasshaus.lan", False),
    ],
)
def test_origin_check(origin: str | None, host: str, ok: bool) -> None:
    assert origin_allowed(origin, host) is ok
