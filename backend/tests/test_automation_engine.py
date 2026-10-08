"""Unit tests for the automation language: schedules, conditions, placeholders, webhook safety."""

import ipaddress
import uuid
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from glasshaus.automation import engine, webhooks
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import Action, Condition, RuleCreate, ScheduleSpec
from glasshaus.projects.models import Project, StatusCategory
from glasshaus.projects.schemas import StatusRead
from glasshaus.tasks.models import Priority
from glasshaus.tasks.schemas import TaskRead

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def make_task(**overrides: object) -> TaskRead:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "key": "WEB-7",
        "project_id": uuid.uuid4(),
        "number": 7,
        "title": "Fix the {{rule.name}} login bug",
        "description": "",
        "status": StatusRead(
            id=uuid.uuid4(),
            name="In progress",
            category=StatusCategory.IN_PROGRESS,
            color="#000000",
            position=2,
        ),
        "priority": Priority.HIGH,
        "assignee_id": None,
        "reporter_id": uuid.uuid4(),
        "parent_id": None,
        "start_date": None,
        "due_date": date(2026, 10, 11),
        "estimate_minutes": None,
        "tags": ["bug", "frontend"],
        "custom_fields": {"f1": 5},
        "position": 1.0,
        "completed_at": None,
        "deleted_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
    }
    return TaskRead.model_validate(base | overrides)


def test_daily_weekly_monthly_schedules() -> None:
    daily = ScheduleSpec(frequency="daily", hour=9, minute=30, timezone="America/Toronto")
    # 12:00 UTC is 08:00 in Toronto (EDT), so today's 09:30 is still ahead.
    assert next_occurrence(daily, NOW) == datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    weekly = ScheduleSpec(frequency="weekly", weekday=0, hour=9)  # Mondays, UTC
    assert next_occurrence(weekly, NOW) == datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    monthly = ScheduleSpec(frequency="monthly", day=8, hour=12)
    assert next_occurrence(monthly, NOW) == datetime(2026, 11, 8, 12, 0, tzinfo=UTC)  # strictly after


def test_schedule_keeps_wall_clock_across_dst() -> None:
    daily = ScheduleSpec(frequency="daily", hour=9, timezone="America/Toronto")
    before = next_occurrence(daily, datetime(2026, 10, 30, 14, 0, tzinfo=UTC))  # EDT (UTC-4)
    after = next_occurrence(daily, datetime(2026, 11, 2, 15, 0, tzinfo=UTC))  # EST (UTC-5)
    assert (before.hour, after.hour) == (13, 14)


def test_schedule_validation() -> None:
    with pytest.raises(ValidationError):
        ScheduleSpec(frequency="weekly")
    with pytest.raises(ValidationError):
        ScheduleSpec(frequency="daily", timezone="Mars/Olympus")


@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("priority", "eq", "HIGH", True),
        ("priority", "in", ["urgent", "high"], True),
        ("status_category", "neq", "done", True),
        ("tags", "contains", "bug", True),
        ("tags", "not_contains", ["docs"], True),
        ("title", "contains", "login", True),
        ("assignee_id", "is_empty", None, True),
        ("due_in_days", "lt", 5, True),
        ("due_in_days", "gt", 5, False),
        ("is_subtask", "eq", False, True),
        ("cf:f1", "gt", "4", False),  # field ids must be UUIDs: rejected by the schema below
    ],
)
def test_conditions(field: str, op: str, value: object, expected: bool) -> None:
    if field.startswith("cf:"):
        with pytest.raises(ValidationError):
            Condition(field=field, op=op, value=value)
        return
    cond = Condition(field=field, op=op, value=value)
    assert engine.condition_holds(cond, make_task(), date(2026, 10, 8)) is expected


def test_custom_field_condition() -> None:
    fid = str(uuid.uuid4())
    task = make_task(custom_fields={fid: 8})
    assert engine.condition_holds(Condition(field=f"cf:{fid}", op="gt", value=5), task, date(2026, 10, 8))


def test_placeholders_are_substituted_not_evaluated() -> None:
    project = Project(id=uuid.uuid4(), key="WEB", name="Website")
    out = engine.render(
        "{{task.key}}: {{task.title}} ({{task.due_date}}) {{unknown}}", make_task(), project, "R1"
    )
    # Placeholders inside task data stay literal; unknown placeholders are left alone.
    assert out == "WEB-7: Fix the {{rule.name}} login bug (2026-10-11) {{unknown}}"


def test_action_shapes() -> None:
    with pytest.raises(ValidationError):
        Action(type="webhook")
    with pytest.raises(ValidationError):
        Action(type="webhook", url="file:///etc/passwd")
    with pytest.raises(ValidationError):
        Action(type="set_status")
    with pytest.raises(ValidationError):
        RuleCreate(name="x", trigger={"type": "due_soon"}, actions=[{"type": "unassign"}])
    rule = RuleCreate(
        name="x", trigger={"type": "status_changed", "to_category": "done"}, actions=[{"type": "unassign"}]
    )
    assert engine.describe(rule.actions[0]) == "unassign"


@pytest.mark.parametrize(
    ("address", "allow_private", "allowed"),
    [
        ("93.184.215.14", False, True),
        ("127.0.0.1", True, False),
        ("169.254.169.254", True, False),
        ("::ffff:127.0.0.1", True, False),
        ("fd00:ec2::254", True, False),
        ("0.0.0.0", True, False),
        ("10.0.0.5", False, False),
        ("10.0.0.5", True, True),
        ("100.101.102.103", True, True),  # CGNAT / Tailscale: private, so opt-in
        ("100.101.102.103", False, False),
    ],
)
def test_webhook_address_policy(address: str, allow_private: bool, allowed: bool) -> None:
    ip = ipaddress.ip_address(address)
    if allowed:
        webhooks.check_address(ip, allow_private=allow_private)
    else:
        with pytest.raises(webhooks.WebhookRefused):
            webhooks.check_address(ip, allow_private=allow_private)


async def test_webhook_refuses_unsafe_urls() -> None:
    for url in ("http://127.0.0.1:9/", "http://169.254.169.254/latest", "http://user:pw@example.com/"):
        result = await webhooks.send(url, {}, secret=None)
        assert not result.ok and result.error


def test_signature_format() -> None:
    sig = webhooks.sign("secret", 1700000000, b'{"a":1}')
    assert sig.startswith("t=1700000000,v1=") and len(sig.split("v1=")[1]) == 64
