"""Unit tests for workload and report maths."""

from datetime import date

from glasshaus.insights import calc

MON = date(2026, 10, 5)  # a Monday
WEEKDAYS = [0, 1, 2, 3, 4]


def test_spread_over_working_days_with_remainder() -> None:
    # Mon..Sun with weekends off: 5 working days, 7 minutes -> 2,2,1,1,1
    out = calc.spread(7, MON, date(2026, 10, 11), WEEKDAYS)
    assert list(out.values()) == [2, 2, 1, 1, 1]
    assert date(2026, 10, 10) not in out and sum(out.values()) == 7


def test_spread_edge_cases() -> None:
    assert calc.spread(60, None, None, WEEKDAYS) == {}
    assert calc.spread(0, MON, MON, WEEKDAYS) == {}
    assert calc.spread(60, None, MON, WEEKDAYS) == {MON: 60}  # due only: one-day task
    saturday = date(2026, 10, 10)
    assert calc.spread(60, saturday, saturday, WEEKDAYS) == {saturday: 60}  # weekend-only span keeps work
    assert calc.spread(2, MON, date(2026, 10, 9), WEEKDAYS) == {MON: 1, date(2026, 10, 6): 1}


def test_capacity_and_buckets() -> None:
    assert calc.capacity(MON, date(2026, 10, 18), 480, WEEKDAYS) == 10 * 480
    assert calc.buckets(date(2026, 10, 7), date(2026, 10, 20), "week") == [
        MON,
        date(2026, 10, 12),
        date(2026, 10, 19),
    ]
    assert calc.bucket_start(date(2026, 10, 11), "week") == MON


def test_burnup_counts_scope_and_done_per_day() -> None:
    tasks = [
        calc.TaskFacts(created=MON, completed=date(2026, 10, 7), deleted=None, cancelled=False),
        calc.TaskFacts(created=date(2026, 10, 6), completed=None, deleted=None, cancelled=False),
        calc.TaskFacts(created=MON, completed=None, deleted=date(2026, 10, 7), cancelled=False),
        calc.TaskFacts(created=MON, completed=None, deleted=None, cancelled=True),
    ]
    assert calc.burnup(tasks, MON, date(2026, 10, 8)) == [
        (MON, 2, 0),
        (date(2026, 10, 6), 3, 0),
        (date(2026, 10, 7), 2, 1),
        (date(2026, 10, 8), 2, 1),
    ]


def test_summary_and_health() -> None:
    assert calc.summary([]) == {"median": None, "p85": None, "average": None}
    stats = calc.summary([1, 2, 3, 4, 10])
    assert stats["median"] == 3 and stats["p85"] == 10 and stats["average"] == 4
    assert calc.health(total=10, done=10, overdue=0, slip_days=0) == "on_track"
    assert calc.health(total=10, done=0, overdue=1, slip_days=0) == "at_risk"
    assert calc.health(total=10, done=5, overdue=1, slip_days=0) == "off_track"  # 1 of 5 open = 20%
    assert calc.health(total=10, done=0, overdue=0, slip_days=8) == "off_track"
    assert calc.health(total=10, done=0, overdue=0, slip_days=2) == "at_risk"
