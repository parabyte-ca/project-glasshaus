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


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    await heartbeat(ctx)
    get_logger(__name__).info("worker.startup", version=__version__)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [heartbeat]
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second={0, 30}, run_at_startup=False)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 30
