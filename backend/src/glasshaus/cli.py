"""Operational CLI: ``glasshaus <command>``."""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.config import Config

from glasshaus.logs import configure_logging, get_logger

ALEMBIC_INI = Path(__file__).resolve().parent / "migrations" / "alembic.ini"


def _alembic_config() -> "Config":
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent))
    return cfg


def cmd_migrate(args: argparse.Namespace) -> None:
    from alembic import command

    from glasshaus.dbroles import ensure_app_role

    command.upgrade(_alembic_config(), args.revision)
    asyncio.run(ensure_app_role())


def cmd_downgrade(args: argparse.Namespace) -> None:
    from alembic import command

    command.downgrade(_alembic_config(), args.revision)


def cmd_seed(args: argparse.Namespace) -> None:
    from glasshaus.seed import run_seed

    asyncio.run(run_seed(demo=args.demo, seed=args.seed))


def cmd_openapi(args: argparse.Namespace) -> None:
    import json

    from glasshaus.main import create_app

    spec = json.dumps(create_app().openapi(), indent=2, sort_keys=False) + "\n"
    if args.output == "-":
        sys.stdout.write(spec)
    else:
        Path(args.output).write_text(spec)


def cmd_wait(args: argparse.Namespace) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from glasshaus.config import get_settings
    from glasshaus.redis_client import ping_redis

    log = get_logger("glasshaus.cli")
    deadline = time.monotonic() + args.timeout
    settings = get_settings()
    # The migrate service waits as the owner: the app role may not exist until migrations have run.
    url = settings.migration_database_url or settings.database_url

    async def probe() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()
        await ping_redis()

    while True:
        try:
            asyncio.run(probe())
            log.info("dependencies.ready")
            return
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() > deadline:
                log.error("dependencies.timeout", error=str(exc))
                sys.exit(1)
            time.sleep(1)


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="glasshaus")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="Apply database migrations")
    p.add_argument("revision", nargs="?", default="head")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("downgrade", help="Revert database migrations")
    p.add_argument("revision")
    p.set_defaults(func=cmd_downgrade)

    p = sub.add_parser("seed", help="Create baseline data (idempotent)")
    p.add_argument("--demo", action="store_true", help="Also generate demo content")
    p.add_argument("--seed", type=int, default=42, help="Random seed for demo data")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("openapi", help="Write the OpenAPI document")
    p.add_argument("output", nargs="?", default="-")
    p.set_defaults(func=cmd_openapi)

    p = sub.add_parser("wait", help="Wait for Postgres and Redis to accept connections")
    p.add_argument("--timeout", type=int, default=60)
    p.set_defaults(func=cmd_wait)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
