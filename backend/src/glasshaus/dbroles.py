"""Database role management: the API/worker/MCP connect as a least-privilege role so Postgres
row-level security is enforced (superusers and BYPASSRLS roles silently skip RLS)."""

import re

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from glasshaus.config import get_settings
from glasshaus.logs import get_logger

log = get_logger(__name__)
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


async def ensure_app_role() -> None:
    settings = get_settings()
    if not settings.migration_database_url:
        return
    app_url = make_url(settings.database_url)
    owner_url = make_url(settings.migration_database_url)
    role, password = app_url.username, app_url.password
    if not role or role == owner_url.username:
        return
    if not _IDENT.match(role) or not password:
        raise SystemExit(f"invalid app database role or missing password in GLASSHAUS_DATABASE_URL: {role!r}")
    engine = create_async_engine(owner_url)
    async with engine.begin() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        verb = "ALTER" if exists else "CREATE"
        # Role names can't be bound parameters; validated against _IDENT above. Password is a literal.
        quoted_pw = "'" + str(password).replace("'", "''") + "'"
        if exists:
            await conn.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD {quoted_pw}"))
        else:
            attrs = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
            await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD {quoted_pw} {attrs}"))
        privileged = await conn.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": role}
        )
        if privileged:
            raise SystemExit(
                f"database role {role} has SUPERUSER or BYPASSRLS; row-level security would not apply"
            )
        db = owner_url.database
        await conn.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO {role}'))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        )
        await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
        await conn.execute(text(f"REVOKE ALL ON alembic_version FROM {role}"))
        # The audit log is append-only: old entries leave only through glasshaus_audit_purge().
        await conn.execute(text(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {role}"))
        dml = "SELECT, INSERT, UPDATE, DELETE"
        await conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {dml} ON TABLES TO {role}"))
    await engine.dispose()
    log.info("db.app_role.ready", role=role, action=verb.lower())


async def check_least_privilege() -> bool:
    """True when the application connection is subject to RLS."""
    from glasshaus.db import get_engine

    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    return not (row.rolsuper or row.rolbypassrls)
