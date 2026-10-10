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


async def automation_tick(ctx: dict[str, Any]) -> dict[str, int]:
    """Time-based automations: scheduled rules and recurring tasks (every minute)."""
    from glasshaus.automation.handlers import run_recurring_tasks, run_scheduled_rules

    return {"scheduled": await run_scheduled_rules(), "recurring": await run_recurring_tasks()}


async def automation_due_soon(ctx: dict[str, Any]) -> int:
    """Due-date reminders; deduplicated per task and due date, so frequent sweeps are safe."""
    from glasshaus.automation.handlers import run_due_soon_rules

    return await run_due_soon_rules()


async def oauth_housekeeping(ctx: dict[str, Any]) -> int:
    """Remove expired OAuth authorization requests, codes and tokens (hourly)."""
    from glasshaus.oauth.service import purge_expired

    return await purge_expired()


async def governance_retention(ctx: dict[str, Any]) -> dict[str, int]:
    """Apply each organization's retention settings (daily)."""
    from glasshaus.governance.service import apply_retention

    return (await apply_retention()).model_dump()


async def integrations_retry(ctx: dict[str, Any]) -> int:
    """Resend integration deliveries whose backoff has elapsed (every minute)."""
    from glasshaus.integrations.delivery import retry_due

    return await retry_due()


async def integrations_email(ctx: dict[str, Any]) -> dict[str, Any]:
    """Email-to-task: poll mailboxes (every two minutes)."""
    from glasshaus.integrations.email import poll_all

    return await poll_all()


async def report_emails(ctx: dict[str, Any]) -> dict[str, int]:
    """Send scheduled report emails that are due."""
    from glasshaus.reports.subscriptions import send_due

    return await send_due()


async def report_alerts(ctx: dict[str, Any]) -> dict[str, int]:
    """Check report alerts that are due."""
    from glasshaus.reports.alerts import check_due

    return await check_due()


async def backup_watch(ctx: dict[str, Any]) -> int:
    """Tell owners and admins about backup problems (once a day per problem)."""
    from glasshaus.backups import watch

    return await watch()


async def release_check(ctx: dict[str, Any]) -> int:
    """Look for a new Glasshaus release once a day and tell owners and admins."""
    from glasshaus.updates import daily_check

    return await daily_check()


async def channel_posts(ctx: dict[str, Any]) -> int:
    """Send scheduled report and status posts to Slack and Teams."""
    from glasshaus.integrations.posts import send_due

    return await send_due()


async def project_assistants(ctx: dict[str, Any]) -> dict[str, int]:
    """Write and deliver the project assistant's digests and weekly drafts that are due."""
    from glasshaus.assistant.service import run_due

    return await run_due()


async def directory_sync(ctx: dict[str, Any]) -> dict[str, int]:
    """Sync managers, job titles and departments from Microsoft Graph (organizations that use it)."""
    from glasshaus.people.graph import nightly

    return await nightly()


async def push_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    """Push new in-app notifications to people's phones and desktops."""
    from glasshaus.push import push_new_notifications

    return await push_new_notifications()


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
    functions: ClassVar[list[Any]] = [
        heartbeat,
        relay_outbox,
        automation_tick,
        automation_due_soon,
        oauth_housekeeping,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 30}, run_at_startup=False),
        cron(relay_outbox, second=set(range(0, 60, 10)), run_at_startup=True),
        cron(automation_tick, second={5}, run_at_startup=True, timeout=300),
        cron(
            automation_due_soon, minute=set(range(0, 60, 10)), second={20}, run_at_startup=True, timeout=300
        ),
        cron(oauth_housekeeping, minute={17}, second={40}, run_at_startup=False),
        cron(governance_retention, hour={3}, minute={23}, second={0}, run_at_startup=False, timeout=900),
        cron(integrations_retry, second={35}, run_at_startup=False, timeout=300),
        cron(report_emails, second={20}, run_at_startup=False, timeout=600),
        cron(report_alerts, second={25}, run_at_startup=False, timeout=600),
        cron(channel_posts, second={15}, run_at_startup=False, timeout=600),
        cron(project_assistants, second={45}, run_at_startup=False, timeout=900),
        cron(push_notifications, second=set(range(3, 60, 10)), run_at_startup=False, timeout=120),
        cron(backup_watch, minute={41}, second={0}, run_at_startup=False),
        cron(release_check, hour={4}, minute={19}, second={30}, run_at_startup=False, timeout=60),
        cron(directory_sync, hour={2}, minute={37}, second={10}, run_at_startup=False, timeout=1800),
        cron(integrations_email, minute=set(range(1, 60, 2)), second={50}, run_at_startup=False, timeout=300),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    health_check_interval = 30
