"""Pure scheduling maths (no I/O): dependency constraints, critical path, forward propagation.

Dates are calendar days. A task occupies ``[start, finish]`` inclusive, so a finish-to-start successor
may begin the day after its predecessor finishes. ``lag`` shifts the constraint (negative = lead).
"""

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta

from glasshaus.scheduling.models import DependencyType


@dataclass(frozen=True, slots=True)
class Edge:
    predecessor: uuid.UUID
    successor: uuid.UUID
    type: DependencyType
    lag: int


@dataclass(slots=True)
class Node:
    id: uuid.UUID
    start: date
    finish: date

    @property
    def duration(self) -> int:
        return (self.finish - self.start).days


@dataclass(slots=True)
class CpmResult:
    early_start: dict[uuid.UUID, date] = field(default_factory=dict)
    early_finish: dict[uuid.UUID, date] = field(default_factory=dict)
    late_start: dict[uuid.UUID, date] = field(default_factory=dict)
    late_finish: dict[uuid.UUID, date] = field(default_factory=dict)
    project_start: date | None = None
    project_finish: date | None = None

    def slack(self, task_id: uuid.UUID) -> int:
        return (self.late_start[task_id] - self.early_start[task_id]).days


def required_start(edge: Edge, pred_start: date, pred_finish: date, succ_duration: int) -> date:
    """Earliest start the successor may have under this dependency."""
    lag = timedelta(days=edge.lag)
    match edge.type:
        case DependencyType.FINISH_TO_START:
            return pred_finish + timedelta(days=1) + lag
        case DependencyType.START_TO_START:
            return pred_start + lag
        case DependencyType.FINISH_TO_FINISH:
            return pred_finish + lag - timedelta(days=succ_duration)
        case DependencyType.START_TO_FINISH:
            return pred_start - timedelta(days=1) + lag - timedelta(days=succ_duration)


def latest_finish(edge: Edge, succ_late_start: date, succ_late_finish: date, pred_duration: int) -> date:
    """Latest finish the predecessor may have without delaying the successor."""
    lag = timedelta(days=edge.lag)
    match edge.type:
        case DependencyType.FINISH_TO_START:
            return succ_late_start - timedelta(days=1) - lag
        case DependencyType.START_TO_START:
            return succ_late_start - lag + timedelta(days=pred_duration)
        case DependencyType.FINISH_TO_FINISH:
            return succ_late_finish - lag
        case DependencyType.START_TO_FINISH:
            return succ_late_finish + timedelta(days=1) - lag + timedelta(days=pred_duration)


def topological_order(nodes: set[uuid.UUID], edges: list[Edge]) -> list[uuid.UUID]:
    """Kahn's algorithm; raises ValueError on a cycle."""
    incoming: dict[uuid.UUID, int] = dict.fromkeys(nodes, 0)
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for e in edges:
        if e.predecessor in nodes and e.successor in nodes:
            incoming[e.successor] += 1
            outgoing[e.predecessor].append(e.successor)
    queue = deque(sorted((n for n, c in incoming.items() if c == 0), key=str))
    order: list[uuid.UUID] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for s in outgoing[n]:
            incoming[s] -= 1
            if incoming[s] == 0:
                queue.append(s)
    if len(order) != len(nodes):
        raise ValueError("dependency cycle")
    return order


def creates_cycle(edges: list[Edge], predecessor: uuid.UUID, successor: uuid.UUID) -> bool:
    """Would adding predecessor -> successor close a loop (successor already reaches predecessor)?"""
    if predecessor == successor:
        return True
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for e in edges:
        outgoing[e.predecessor].append(e.successor)
    seen: set[uuid.UUID] = set()
    stack = [successor]
    while stack:
        n = stack.pop()
        if n == predecessor:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(outgoing[n])
    return False


def critical_path(nodes: dict[uuid.UUID, Node], edges: list[Edge]) -> CpmResult:
    """Forward/backward pass. Planned starts act as 'start no earlier than' constraints."""
    result = CpmResult()
    if not nodes:
        return result
    live = [e for e in edges if e.predecessor in nodes and e.successor in nodes]
    order = topological_order(set(nodes), live)
    preds: dict[uuid.UUID, list[Edge]] = defaultdict(list)
    succs: dict[uuid.UUID, list[Edge]] = defaultdict(list)
    for e in live:
        preds[e.successor].append(e)
        succs[e.predecessor].append(e)

    for n in order:
        node = nodes[n]
        es = node.start
        for e in preds[n]:
            es = max(
                es,
                required_start(
                    e, result.early_start[e.predecessor], result.early_finish[e.predecessor], node.duration
                ),
            )
        result.early_start[n] = es
        result.early_finish[n] = es + timedelta(days=node.duration)
    result.project_start = min(result.early_start.values())
    result.project_finish = max(result.early_finish.values())

    for n in reversed(order):
        node = nodes[n]
        lf = result.project_finish
        for e in succs[n]:
            lf = min(
                lf,
                latest_finish(
                    e, result.late_start[e.successor], result.late_finish[e.successor], node.duration
                ),
            )
        result.late_finish[n] = lf
        result.late_start[n] = lf - timedelta(days=node.duration)
    return result


def propagate(
    nodes: dict[uuid.UUID, Node], edges: list[Edge], changed: set[uuid.UUID] | None = None
) -> dict[uuid.UUID, Node]:
    """Push successors later (never earlier) until every dependency holds; durations are kept.

    Returns the moved nodes with their new dates. ``changed`` limits the walk to their descendants.
    """
    live = [e for e in edges if e.predecessor in nodes and e.successor in nodes]
    order = topological_order(set(nodes), live)
    preds: dict[uuid.UUID, list[Edge]] = defaultdict(list)
    for e in live:
        preds[e.successor].append(e)
    current = {k: Node(v.id, v.start, v.finish) for k, v in nodes.items()}
    dirty = set(changed) if changed is not None else set(nodes)
    moved: dict[uuid.UUID, Node] = {}
    for n in order:
        incoming = preds[n]
        if changed is not None and not any(e.predecessor in dirty for e in incoming):
            continue
        node = current[n]
        need = node.start
        for e in incoming:
            p = current[e.predecessor]
            need = max(need, required_start(e, p.start, p.finish, node.duration))
        if need > node.start:
            shift = need - node.start
            node.start, node.finish = node.start + shift, node.finish + shift
            moved[n] = node
            dirty.add(n)
    return moved


def violations(nodes: dict[uuid.UUID, Node], edges: list[Edge]) -> list[tuple[Edge, int]]:
    """Dependencies not satisfied by the current dates, with how many days the successor is early."""
    out: list[tuple[Edge, int]] = []
    for e in edges:
        p, s = nodes.get(e.predecessor), nodes.get(e.successor)
        if p is None or s is None:
            continue
        need = required_start(e, p.start, p.finish, s.duration)
        if s.start < need:
            out.append((e, (need - s.start).days))
    return out
