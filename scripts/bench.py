#!/usr/bin/env python3
"""Latency benchmark for common API calls (target: p95 under 200 ms).

    GLASSHAUS_TOKEN=ghp_... python3 scripts/bench.py --url http://localhost:8471 --project WEB \
        [--seed 2000] [--requests 300] [--concurrency 10]

Requests over the API rate limit (GLASSHAUS_API_RATE_LIMIT_PER_MINUTE) wait and retry; only served
requests are timed. --seed first creates that many tasks in the project so lists and reports run on realistic volume.
Exits non-zero when any endpoint's p95 exceeds --budget-ms. Needs only httpx.
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import time

import httpx


async def call(client: httpx.AsyncClient, method: str, path: str, **kw: object) -> tuple[httpx.Response, float]:
    """One request; waits out the API rate limit (429) so only served requests are timed."""
    while True:
        start = time.perf_counter()
        r = await client.request(method, path, **kw)  # type: ignore[arg-type]
        elapsed = (time.perf_counter() - start) * 1000
        if r.status_code != 429:
            return r, elapsed
        await asyncio.sleep(float(r.headers.get("retry-after", "5")))


async def seed(client: httpx.AsyncClient, project_id: str, count: int) -> None:
    sem = asyncio.Semaphore(10)

    async def one(i: int) -> None:
        async with sem:
            r, _ = await call(
                client, "POST", "/api/v1/tasks",
                json={"project_id": project_id, "title": f"Bench task {i}", "priority": random.choice(["low", "medium", "high"]),
                      "estimate_minutes": random.choice([30, 60, 120, 240])},
            )  # fmt: skip
            r.raise_for_status()

    await asyncio.gather(*(one(i) for i in range(count)))


async def measure(client: httpx.AsyncClient, method: str, path: str, n: int, concurrency: int, **kw: object) -> list[float]:
    sem = asyncio.Semaphore(concurrency)
    times: list[float] = []

    async def one() -> None:
        async with sem:
            r, elapsed = await call(client, method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
            times.append(elapsed)

    await asyncio.gather(*(one() for _ in range(n)))
    return times


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("GLASSHAUS_API_URL", "http://localhost:8471"))
    parser.add_argument("--project", required=True, help="project key")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--budget-ms", type=float, default=200.0)
    args = parser.parse_args()
    token = os.environ.get("GLASSHAUS_TOKEN")
    if not token:
        print("set GLASSHAUS_TOKEN to an API token with read and tasks:write", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(base_url=args.url, headers=headers, timeout=30, limits=limits) as client:
        project = (await client.get(f"/api/v1/projects/by-key/{args.project}")).raise_for_status().json()
        pid = project["id"]
        if args.seed:
            started = time.perf_counter()
            await seed(client, pid, args.seed)
            print(f"seeded {args.seed} tasks in {time.perf_counter() - started:.1f}s")
        page = (await client.get("/api/v1/tasks", params={"project_id": pid, "limit": 1})).json()
        ref = page["items"][0]["key"]
        task_id = page["items"][0]["id"]
        cases = [
            ("GET", "/api/v1/projects", {}),
            ("GET", "/api/v1/tasks", {"params": {"project_id": pid, "limit": 100}}),
            ("GET", "/api/v1/tasks", {"params": {"project_id": pid, "limit": 50, "q": "Bench 1"}}),
            ("GET", f"/api/v1/tasks/{ref}", {}),
            ("GET", f"/api/v1/projects/{pid}/schedule", {}),
            ("GET", f"/api/v1/projects/{pid}/report", {}),
            ("GET", f"/api/v1/projects/{pid}/status-summary", {}),
            ("GET", "/api/v1/workload", {"params": {"project_id": pid}}),
            ("GET", "/api/v1/notifications/unread-count", {}),
            ("PATCH", f"/api/v1/tasks/{task_id}", {"json": {"priority": "high"}}),
        ]
        rows, failed = [], False
        for method, path, kw in cases:
            await measure(client, method, path, 5, 1, **kw)  # warm up
            times = await measure(client, method, path, args.requests, args.concurrency, **kw)
            p95 = pct(times, 95)
            failed |= p95 > args.budget_ms
            label = f"{method} {path.replace(pid, '{id}').replace(ref, '{ref}').replace(task_id, '{id}')}"
            if kw.get("params"):
                label += "?" + "&".join(f"{k}=…" for k in kw["params"])  # type: ignore[union-attr]
            rows.append((label, statistics.median(times), p95, pct(times, 99), max(times)))
    width = max(len(r[0]) for r in rows)
    print(f"{'endpoint':<{width}}  {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}  (ms, {args.requests} req, c={args.concurrency})")
    for label, p50, p95, p99, top in rows:
        flag = "  ✗ over budget" if p95 > args.budget_ms else ""
        print(f"{label:<{width}}  {p50:7.1f} {p95:7.1f} {p99:7.1f} {top:7.1f}{flag}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
