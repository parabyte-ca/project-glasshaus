import uuid
from datetime import date, timedelta

import pytest

from glasshaus.scheduling.cpm import Edge, Node, creates_cycle, critical_path, propagate, violations
from glasshaus.scheduling.models import DependencyType as T

D0 = date(2026, 1, 5)


def node(start_offset: int, days: int) -> Node:
    start = D0 + timedelta(days=start_offset)
    return Node(uuid.uuid4(), start, start + timedelta(days=days - 1))


def test_finish_to_start_chain_is_critical_and_side_branch_has_slack() -> None:
    a, b, c, side = node(0, 3), node(3, 2), node(5, 4), node(3, 1)
    nodes = {n.id: n for n in (a, b, c, side)}
    edges = [
        Edge(a.id, b.id, T.FINISH_TO_START, 0),
        Edge(b.id, c.id, T.FINISH_TO_START, 0),
        Edge(a.id, side.id, T.FINISH_TO_START, 0),
    ]
    r = critical_path(nodes, edges)
    assert r.project_start == D0 and r.project_finish == date(2026, 1, 13)
    assert [r.slack(x.id) for x in (a, b, c)] == [0, 0, 0]
    assert r.slack(side.id) == 5  # can slip until the project finish


@pytest.mark.parametrize(
    ("kind", "lag", "expected_start"),
    [
        (T.FINISH_TO_START, 0, date(2026, 1, 8)),  # day after A finishes (A: 5th-7th)
        (T.FINISH_TO_START, 2, date(2026, 1, 10)),  # 2-day gap
        (T.FINISH_TO_START, -1, date(2026, 1, 7)),  # 1-day lead
        (T.START_TO_START, 1, date(2026, 1, 6)),
        (T.FINISH_TO_FINISH, 0, date(2026, 1, 6)),  # B (2 days) must finish no earlier than A's finish
        (T.START_TO_FINISH, 0, date(2026, 1, 3)),  # B finishes the day before A starts (clamped by own start)
    ],
)
def test_dependency_types_and_lag(kind: T, lag: int, expected_start: date) -> None:
    a = node(0, 3)
    b = Node(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 2))  # 2-day task planned early
    moved = propagate({a.id: a, b.id: b}, [Edge(a.id, b.id, kind, lag)])
    new_start = moved[b.id].start if b.id in moved else b.start
    assert new_start == max(expected_start, b.start)
    if b.id in moved:
        assert moved[b.id].duration == 1  # duration preserved


def test_propagate_only_pushes_later_and_cascades() -> None:
    a, b, c = node(0, 2), node(10, 2), node(11, 1)
    edges = [Edge(a.id, b.id, T.FINISH_TO_START, 0), Edge(b.id, c.id, T.FINISH_TO_START, 0)]
    nodes = {n.id: n for n in (a, b, c)}
    assert propagate(nodes, edges) == {c.id: Node(c.id, date(2026, 1, 17), date(2026, 1, 17))}
    a.finish = date(2026, 1, 20)
    moved = propagate(nodes, edges, changed={a.id})
    assert moved[b.id].start == date(2026, 1, 21) and moved[c.id].start == date(2026, 1, 23)


def test_cycles_and_violations() -> None:
    a, b, c = (uuid.uuid4() for _ in range(3))
    edges = [Edge(a, b, T.FINISH_TO_START, 0), Edge(b, c, T.FINISH_TO_START, 0)]
    assert creates_cycle(edges, c, a) and creates_cycle(edges, a, a)
    assert not creates_cycle(edges, a, c)
    x, y = node(0, 3), node(1, 1)
    assert [
        (e.successor, d) for e, d in violations({x.id: x, y.id: y}, [Edge(x.id, y.id, T.FINISH_TO_START, 0)])
    ] == [(y.id, 2)]
