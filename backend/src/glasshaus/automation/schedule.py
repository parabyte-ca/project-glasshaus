"""Next-occurrence calculation for daily/weekly/monthly schedules in an IANA time zone."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from glasshaus.automation.schemas import Frequency, ScheduleSpec


def next_occurrence(spec: ScheduleSpec, after: datetime) -> datetime:
    """First occurrence strictly after ``after`` (aware datetime), returned in UTC."""
    tz = ZoneInfo(spec.timezone)
    local = after.astimezone(tz)
    candidate = local.replace(hour=spec.hour, minute=spec.minute, second=0, microsecond=0)
    for _ in range(400):  # bounded search: at most ~13 months of days
        ok = True
        if spec.frequency == Frequency.WEEKLY:
            ok = candidate.weekday() == spec.weekday
        elif spec.frequency == Frequency.MONTHLY:
            ok = candidate.day == spec.day
        if ok and candidate > local:
            # Re-anchor in the zone so DST transitions keep the wall-clock time.
            return candidate.replace(tzinfo=tz).astimezone(UTC)
        candidate = (candidate + timedelta(days=1)).replace(hour=spec.hour, minute=spec.minute)
    raise ValueError("no occurrence found")  # pragma: no cover
