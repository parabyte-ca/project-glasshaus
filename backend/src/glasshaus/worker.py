"""arq background worker: async jobs and cron schedules.

Run with ``arq glasshaus.worker.WorkerSettings``.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from glasshaus.config import get_settings
from glasshaus.logs import configure_logging, get_logger
from glasshaus.redis_client import get_redis
from glasshaus.version import __version__

HEARTBEAT_KEY = "glasshaus:worker:heartbeat"


async def heartbeat(ctx: dict[str, Any]) -> str:
    """Record liveness so the container healthcheck can verify the worker loop is running."""
    now = datetime.now(UTC).isoformat()
    await get_redis().set(HEARTBEAT_KEY, now, ex=180)
    return now


async def relay_outbox(ctx: dict[str, Any]) -> int:
    """Sweep domain events whose post-commit relay failed."""
    from glasshaus.core.events import relay_events

    return await relay_events()


async def startup(ctx: dict[str, Any]) -> None:
    import asyncio

    from glasshaus.core.consumers import consume

    configure_logging()
    await heartbeat(ctx)
    ctx["consumer_stop"] = asyncio.Event()
    ctx["consumer_task"] = asyncio.create_task(consume(ctx["consumer_stop"]))
    get_logger(__name__).info("worker.startup", version=__version__)


async def shutdown(ctx: dict[str, Any]) -> None:
    import asyncio
    import contextlib

    ctx["consumer_stop"].set()
    task: asyncio.Task[None] = ctx["consumer_task"]
    try:
        await asyncio.wait_for(task, timeout=10)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class WorkerSettings:
    functions: ClassVar[list[Any]] = [heartbeat, relay_outbox]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 30}, run_at_startup=False),
        cron(relay_outbox, second=set(range(0, 60, 10)), run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 30
