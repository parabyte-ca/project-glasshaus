"""Event consumer batching: different aggregates in parallel, one aggregate in stream order."""

import asyncio
from typing import Any

import orjson
import pytest

from glasshaus import redis_client
from glasshaus.core import consumers


class FakeRedis:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def xack(self, stream: str, group: str, entry_id: str) -> None:
        self.acked.append(entry_id)


def entry(n: int, aggregate: str) -> tuple[str, dict[str, str]]:
    event = {"id": f"e{n}", "type": "task.updated", "aggregate_type": "task", "aggregate_id": aggregate}
    return f"{n}-0", {"event": orjson.dumps(event).decode()}


async def test_batches_run_aggregates_in_parallel_and_each_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: redis)
    seen: dict[str, list[str]] = {}
    running = 0
    peak = 0

    async def dispatch(event: dict[str, Any]) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        seen.setdefault(event["aggregate_id"], []).append(event["id"])
        running -= 1

    monkeypatch.setattr(consumers, "dispatch", dispatch)
    entries = [entry(n, f"t{n % 4}") for n in range(20)] + [(("20-0"), {"event": "not json"})]
    await consumers.process_batch(entries, concurrency=3)

    assert peak == 3
    for aggregate, ids in seen.items():
        expected = [f"e{n}" for n in range(20) if f"t{n % 4}" == aggregate]
        assert ids == expected
    # Every readable entry is acknowledged; the unreadable one stays pending for retry/dead-letter.
    assert sorted(redis.acked) == sorted(f"{n}-0" for n in range(20))
