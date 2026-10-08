"""Pure, I/O-free maths for workload and reports (unit tested directly)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)] if start <= end else []


def bucket_start(day: date, bucket: str) -> date:
    """Monday of the week for weekly buckets, the day itself for daily buckets."""
    return day - timedelta(days=day.weekday()) if bucket == "week" else day


def buckets(start: date, end: date, bucket: str) -> list[date]:
    return sorted({bucket_start(d, bucket) for d in days_between(start, end)})


def spread(
    minutes: int, start: date | None, due: date | None, working_days: Iterable[int]
) -> dict[date, int]:
    """Spread remaining work evenly over the task's working days (start..due, inclusive).

    A task with one date is a one-day task. If its span has no working days the whole span is used,
    so work never disappears. Rounding remainders go to the earliest days.
    """
    if minutes <= 0 or (start is None and due is None):
        return {}
    first = start or due
    last = due or start
    assert first is not None
    assert last is not None
    if last < first:
        first, last = last, first
    worked = set(working_days)
    span = [d for d in days_between(first, last) if d.weekday() in worked] or days_between(first, last)
    share, extra = divmod(minutes, len(span))
    return {d: share + (1 if i < extra else 0) for i, d in enumerate(span) if share or i < extra}


def capacity(start: date, end: date, per_day: int, working_days: Iterable[int]) -> int:
    worked = set(working_days)
    return per_day * sum(1 for d in days_between(start, end) if d.weekday() in worked)


@dataclass(frozen=True)
class TaskFacts:
    created: date
    completed: date | None  # set when the task is currently done
    deleted: date | None
    cancelled: bool


def burnup(tasks: Iterable[TaskFacts], start: date, end: date) -> list[tuple[date, int, int]]:
    """(day, scope, done) per day. Scope counts tasks that existed that day (cancelled tasks excluded);
    done counts tasks completed on or before the day. Based on current state, not full history."""
    facts = [t for t in tasks if not t.cancelled]
    out = []
    for day in days_between(start, end):
        scope = sum(1 for t in facts if t.created <= day and (t.deleted is None or t.deleted > day))
        done = sum(
            1
            for t in facts
            if t.completed is not None and t.completed <= day and (t.deleted is None or t.deleted > day)
        )
        out.append((day, scope, done))
    return out


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (pct in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(pct / 100 * len(ordered) + 0.5)))
    return ordered[rank - 1]


def summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p85": None, "average": None}
    return {
        "median": float(median(values)),
        "p85": percentile(values, 85),
        "average": round(sum(values) / len(values), 2),
    }


def health(total: int, done: int, overdue: int, slip_days: int) -> str:
    """Rule of thumb for portfolio rollups: off track when a fifth of open work is overdue or the plan
    has slipped more than a week; at risk with any overdue work or slip; otherwise on track."""
    open_tasks = max(total - done, 0)
    if open_tasks and (overdue / open_tasks >= 0.2 or slip_days > 7):
        return "off_track"
    if overdue or slip_days > 0:
        return "at_risk"
    return "on_track"
