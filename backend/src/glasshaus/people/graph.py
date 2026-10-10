"""Microsoft Graph directory sync: managers, job titles and departments from Microsoft Entra ID.

For organizations whose identity provider does not send managers over SCIM. An org admin registers
an app in Entra ID with the User.Read.All application permission and enters its IDs and secret in
Admin > Provisioning. Each night (and on "Sync now") Glasshaus reads the directory and matches
people by email. SCIM wins: someone whose manager came from SCIM is left alone.

Only the two fixed Microsoft hosts are called, the directory ID is a plain name (no path tricks),
and paging links are followed only on graph.microsoft.com.
"""

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from glasshaus.core import crypto
from glasshaus.core.authz import require_org
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, RateLimited, ServiceError
from glasshaus.core.rbac import Permission
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import ASSISTANT_KIND, User
from glasshaus.logs import get_logger
from glasshaus.people.models import DirectorySync
from glasshaus.people.schemas import DirectorySyncRead, DirectorySyncWrite
from glasshaus.people.service import set_manager

log = get_logger(__name__)

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com"
USERS_URL = (
    f"{GRAPH}/v1.0/users?$select=id,mail,userPrincipalName,jobTitle,department"
    "&$expand=manager($select=id)&$top=999"
)
MAX_PAGES = 200
TIMEOUT = 30


class SyncError(ServiceError):
    code = "directory_sync_failed"
    status = 502


# --------------------------------------------------------------------------- settings (org admins)


async def _row(ctx: ServiceContext) -> DirectorySync:
    row = await ctx.session.get(DirectorySync, ctx.tenant_id)
    if row is None:
        row = DirectorySync(tenant_id=ctx.tenant_id)
        ctx.session.add(row)
        await ctx.session.flush()
    return row


def _read(row: DirectorySync) -> DirectorySyncRead:
    return DirectorySyncRead(
        enabled=row.enabled,
        directory_id=row.directory_id,
        client_id=row.client_id,
        client_secret=crypto.mask(row.client_secret),
        last_run_at=row.last_run_at,
        last_error=row.last_error,
        last_result={k: int(v) for k, v in (row.last_result or {}).items()},
    )


async def get_settings(ctx: ServiceContext) -> DirectorySyncRead:
    require_org(ctx, Permission.ORG_MANAGE)
    return _read(await _row(ctx))


async def update_settings(ctx: ServiceContext, data: DirectorySyncWrite) -> DirectorySyncRead:
    require_org(ctx, Permission.ORG_MANAGE)
    row = await _row(ctx)
    row.directory_id, row.client_id = data.directory_id, data.client_id
    if data.client_secret is not None:
        row.client_secret = crypto.encrypt(data.client_secret) if data.client_secret else None
    if data.enabled and not (row.directory_id and row.client_id and row.client_secret):
        raise InvalidInput("enter the directory ID, client ID and client secret to turn the sync on")
    row.enabled = data.enabled
    from glasshaus.core import events

    events.emit(
        ctx,
        "directory_sync.updated",
        "directory_sync",
        ctx.tenant_id,
        {"enabled": row.enabled, "directory_id": row.directory_id, "client_id": row.client_id},
    )
    await ctx.session.flush()
    return _read(row)


# --------------------------------------------------------------------------- reading the directory


async def _token(client: httpx.AsyncClient, directory_id: str, client_id: str, secret: str) -> str:
    r = await client.post(
        f"{LOGIN}/{directory_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "scope": f"{GRAPH}/.default",
        },
    )
    if r.status_code != 200:
        detail = ""
        with contextlib.suppress(ValueError):
            detail = str(r.json().get("error_description", ""))[:200]
        raise SyncError(f"Entra ID refused the app's sign-in (HTTP {r.status_code}). {detail}".strip())
    token = r.json().get("access_token")
    if not isinstance(token, str):
        raise SyncError("Entra ID sent no access token")
    return token


async def fetch_directory(directory_id: str, client_id: str, secret: str) -> list[dict[str, Any]]:
    """Every user in the directory: id, emails, job title, department and their manager's id."""
    people: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        token = await _token(client, directory_id, client_id, secret)
        url: str | None = USERS_URL
        for _ in range(MAX_PAGES):
            if url is None:
                break
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 403:
                raise SyncError("the app needs the User.Read.All application permission (admin consent)")
            if r.status_code != 200:
                raise SyncError(f"Microsoft Graph answered HTTP {r.status_code}")
            body = r.json()
            for u in body.get("value") or []:
                manager = u.get("manager") or {}
                people.append(
                    {
                        "id": u.get("id"),
                        "emails": {
                            e.strip().lower()
                            for e in (u.get("mail"), u.get("userPrincipalName"))
                            if isinstance(e, str) and "@" in e
                        },
                        "job_title": u.get("jobTitle"),
                        "department": u.get("department"),
                        "manager": manager.get("id") if isinstance(manager, dict) else None,
                    }
                )
            nxt = body.get("@odata.nextLink")
            url = nxt if isinstance(nxt, str) and nxt.startswith(f"{GRAPH}/") else None
    return people


async def apply(ctx: ServiceContext, directory: list[dict[str, Any]]) -> dict[str, int]:
    """Match the directory to people here by email and record managers, titles and departments."""
    users = (
        await ctx.session.scalars(select(User).where(User.kind != ASSISTANT_KIND, User.is_active.is_(True)))
    ).all()
    by_email = {u.email.lower(): u for u in users}
    ours: dict[str, User] = {}  # Graph id -> person here
    for entry in directory:
        match = next((by_email[e] for e in entry["emails"] if e in by_email), None)
        if match is not None and entry["id"]:
            ours[entry["id"]] = match
    result = {"matched": len(ours), "managers": 0, "cleared": 0, "skipped": 0}
    for entry in directory:
        person = ours.get(entry["id"])
        if person is None:
            continue
        if person.manager_source == "scim":
            result["skipped"] += 1  # the identity provider sends this person's manager itself
            continue
        title = (entry["job_title"] or "").strip()[:200] or None
        dept = (entry["department"] or "").strip()[:200] or None
        person.job_title, person.department = title, dept
        manager = ours.get(entry["manager"]) if entry["manager"] else None
        if manager is not None:
            if person.manager_id != manager.id:
                if await set_manager(ctx.session, person, manager.id, "graph"):
                    result["managers"] += 1
            else:
                person.manager_source = "graph"
        elif person.manager_id is not None and person.manager_source == "graph":
            await set_manager(ctx.session, person, None, "graph")
            result["cleared"] += 1
    await ctx.session.flush()
    return result


async def sync(tenant_id: uuid.UUID) -> dict[str, int]:
    """Read the directory (outside any transaction), then apply it and record the outcome."""
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        row = await ctx.session.get(DirectorySync, tenant_id)
        if row is None or not (row.directory_id and row.client_id and row.client_secret):
            raise InvalidInput("set up the directory sync first")
        directory_id, client_id, secret = row.directory_id, row.client_id, crypto.decrypt(row.client_secret)
    error: str | None = None
    result: dict[str, int] = {}
    try:
        directory = await fetch_directory(directory_id, client_id, secret)
        async with unit_of_work(Actor.system(tenant_id)) as ctx:
            result = await apply(ctx, directory)
    except ServiceError as exc:
        error = str(exc)
    except httpx.HTTPError as exc:
        error = f"could not reach Microsoft ({type(exc).__name__})"
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        row = await ctx.session.get(DirectorySync, tenant_id)
        if row is not None:
            row.last_run_at, row.last_error = datetime.now(UTC), error
            if not error:
                row.last_result = result
    if error:
        log.warning("people.graph_sync_failed", tenant=str(tenant_id), error=error)
        raise SyncError(error)
    log.info("people.graph_sync", tenant=str(tenant_id), **result)
    return result


async def sync_now(actor: Actor) -> DirectorySyncRead:
    """Admin button: run the sync now (at most once a minute per organization)."""
    from glasshaus.redis_client import get_redis

    async with unit_of_work(actor) as ctx:
        require_org(ctx, Permission.ORG_MANAGE)
    key = f"glasshaus:graph-sync:{actor.tenant_id}:{int(datetime.now(UTC).timestamp() // 60)}"
    try:
        redis = get_redis()
        if await redis.incr(key) > 1:
            raise RateLimited("a sync ran in the last minute; try again shortly")
        await redis.expire(key, 90)
    except RateLimited:
        raise
    except Exception:
        log.warning("people.rate_limit_unavailable", exc_info=True)
    with contextlib.suppress(SyncError):  # recorded on the settings; shown to the admin below
        await sync(actor.tenant_id)
    async with unit_of_work(actor) as ctx:
        return _read(await _row(ctx))


async def nightly() -> dict[str, int]:
    """Worker job: sync every organization that turned it on."""
    async with system_session() as session:
        tenants = (
            await session.scalars(select(DirectorySync.tenant_id).where(DirectorySync.enabled.is_(True)))
        ).all()
    ok = 0
    for tenant_id in tenants:
        try:
            await sync(tenant_id)
            ok += 1
        except Exception:  # one organization's directory must not stop the others
            log.warning("people.graph_sync_error", tenant=str(tenant_id), exc_info=True)
    return {"organizations": len(tenants), "ok": ok}
