"""Integrations: administration, outbound delivery (Slack, Microsoft Teams, signed webhooks), inbound
GitHub/GitLab events and email-to-task, and personal iCalendar feeds (Google, Microsoft 365, Apple).

Secrets (webhook URLs, signing secrets, mailbox passwords) are encrypted at rest and never returned.
Text from tasks and comments is user content: it is escaped and truncated in outgoing messages, and
inbound text only ever becomes task or comment content, never instructions.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import Field, HttpUrl, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.config import get_settings
from glasshaus.core import crypto, events
from glasshaus.core.authz import require_org, require_project
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied, Unauthenticated
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.core.schemas import Schema
from glasshaus.identity import security
from glasshaus.integrations.models import CalendarFeed, Integration, IntegrationDelivery

Kind = Literal["slack", "teams", "webhook", "github", "gitlab", "email", "slack_command"]
OUTBOUND: frozenset[str] = frozenset({"slack", "teams", "webhook"})
INBOUND: frozenset[str] = frozenset({"github", "gitlab", "email"})
EVENT_TYPES = [
    "task.created",
    "task.updated",
    "task.completed",
    "task.deleted",
    "task.restored",
    "comment.created",
    "dependency.created",
    "project.created",
    "project.updated",
    "project.imported",
    "time.logged",
    "automation.failed",
]
DEFAULT_EVENTS = ["task.created", "task.completed", "comment.created"]
MAX_ATTEMPTS = 6
BACKOFF = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=4),
]
REF = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,7})\b")
CLOSES = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#?([A-Z][A-Z0-9]{1,9}-\d{1,7})\b", re.IGNORECASE
)


# --------------------------------------------------------------------------- schemas


class EmailConfig(Schema):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    folder: str = Field("INBOX", max_length=200)
    allowed_senders: list[str] = Field(
        default_factory=list, max_length=100, description="Sender addresses or @domains allowed (empty: any)."
    )


class IntegrationCreate(Schema):
    kind: Kind
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    project_id: uuid.UUID | None = Field(
        None, description="Outbound: only this project's events. Inbound: required."
    )
    events: list[str] = Field(
        default_factory=list, max_length=50, description="Outbound event types (empty: defaults)."
    )
    url: HttpUrl | None = Field(None, description="slack/teams: incoming webhook URL. webhook: target URL.")
    secret: str | None = Field(
        None,
        max_length=500,
        description=(
            "webhook/github/gitlab: signing secret (generated if empty). email: password. "
            "slack_command: the Slack app's signing secret."
        ),
    )
    token: str | None = Field(
        None, max_length=500, description="slack_command: the Slack app's bot token (xoxb-…)."
    )
    email: EmailConfig | None = None

    @model_validator(mode="after")
    def _check(self) -> "IntegrationCreate":
        unknown = set(self.events) - set(EVENT_TYPES)
        if unknown:
            raise ValueError(f"unknown event types: {', '.join(sorted(unknown))}")
        if self.kind in OUTBOUND and self.url is None:
            raise ValueError(f"{self.kind} needs a url")
        if self.kind in INBOUND and self.project_id is None:
            raise ValueError(f"{self.kind} needs a project_id (where tasks and links go)")
        if self.kind == "email" and (self.email is None or not self.secret):
            raise ValueError("email needs mailbox settings and a password")
        if self.kind == "slack_command":
            if not self.secret or not self.token:
                raise ValueError("slack_command needs the Slack app's signing secret and bot token")
            if self.project_id is not None:
                raise ValueError("slack_command covers the whole organization; leave project_id empty")
        return self


class IntegrationUpdate(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    enabled: bool | None = None
    events: list[str] | None = Field(None, max_length=50)
    url: HttpUrl | None = None
    secret: str | None = Field(None, max_length=500)
    token: str | None = Field(None, max_length=500, description="slack_command: a new bot token.")
    email: EmailConfig | None = None


class IntegrationRead(Schema):
    id: uuid.UUID
    kind: Kind
    name: str
    enabled: bool
    project_id: uuid.UUID | None
    events: list[str]
    url_host: str | None = Field(description="Host of the target URL (the URL itself is secret).")
    secret_set: bool
    inbound_url: str | None = Field(
        description="github/gitlab: the payload URL. slack_command: the slash command's Request URL."
    )
    email: EmailConfig | None
    last_success_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    created_at: datetime


class IntegrationCreated(IntegrationRead):
    signing_secret: str | None = Field(description="Shown once when Glasshaus generated it.")


class DeliveryRead(Schema):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    response_status: int | None
    error: str | None
    created_at: datetime
    delivered_at: datetime | None
    next_attempt_at: datetime | None


class CalendarFeedRead(Schema):
    url: str | None = Field(description="Only returned when the feed is created; keep it private.")
    created_at: datetime | None
    last_used_at: datetime | None


# --------------------------------------------------------------------------- helpers


def _base() -> str:
    return get_settings().public_url.rstrip("/")


def inbound_url(integration_id: uuid.UUID, kind: str = "github") -> str:
    tail = "slack" if kind == "slack_command" else "inbound"
    return f"{_base()}/api/v1/integrations/{integration_id}/{tail}"


def _read(i: Integration) -> IntegrationRead:
    host = i.config.get("url_host")
    return IntegrationRead(
        id=i.id,
        kind=i.kind,
        name=i.name,
        enabled=i.enabled,
        project_id=i.project_id,
        events=list(i.events),
        url_host=host,
        secret_set=bool(i.secret),
        inbound_url=inbound_url(i.id, i.kind) if i.kind in ("github", "gitlab", "slack_command") else None,
        email=EmailConfig.model_validate(i.config["email"]) if i.kind == "email" else None,
        last_success_at=i.last_success_at,
        last_error=i.last_error,
        last_error_at=i.last_error_at,
        created_at=i.created_at,
    )


async def _authorize(ctx: ServiceContext, project_id: uuid.UUID | None) -> None:
    """Org admins manage any integration; project admins manage their project's."""
    if project_id is None:
        require_org(ctx, Permission.ORG_MANAGE)
    elif not ctx.actor.is_org_admin:
        await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    elif (
        ctx.actor.scopes is not None
        and "admin" not in ctx.actor.scopes
        and "projects:write" not in ctx.actor.scopes
    ):
        raise PermissionDenied("this needs the projects:write scope")


def _secrets_of(i: Integration) -> dict[str, str]:
    return {} if not i.secret else dict(re.findall(r"(\w+)=([^\n]*)", crypto.decrypt(i.secret)))


def _store_secrets(values: dict[str, str]) -> str | None:
    clean = {k: v for k, v in values.items() if v}
    if not clean:
        return None
    if any("\n" in v for v in clean.values()):
        raise InvalidInput("secrets cannot contain line breaks")
    return crypto.encrypt("\n".join(f"{k}={v}" for k, v in clean.items()))


# --------------------------------------------------------------------------- administration


async def list_integrations(
    ctx: ServiceContext, project_id: uuid.UUID | None = None
) -> list[IntegrationRead]:
    if project_id is not None:
        await _authorize(ctx, project_id)
        stmt = select(Integration).where(Integration.project_id == project_id)
    else:
        require_org(ctx, Permission.ORG_MANAGE)
        stmt = select(Integration)
    rows = await ctx.session.scalars(stmt.order_by(Integration.created_at))
    return [_read(i) for i in rows.all()]


async def _get(ctx: ServiceContext, integration_id: uuid.UUID) -> Integration:
    i = await ctx.session.get(Integration, integration_id)
    if i is None:
        raise NotFound("integration not found")
    await _authorize(ctx, i.project_id)
    return i


async def get_integration(ctx: ServiceContext, integration_id: uuid.UUID) -> IntegrationRead:
    return _read(await _get(ctx, integration_id))


async def create_integration(ctx: ServiceContext, data: IntegrationCreate) -> IntegrationCreated:
    await _authorize(ctx, data.project_id)
    if data.kind in ("email", "slack_command"):
        # The server connects to the mail host / answers for the whole organization: org admins only.
        require_org(ctx, Permission.ORG_MANAGE)
    generated: str | None = None
    values: dict[str, str] = {}
    config: dict[str, Any] = {}
    if data.url is not None:
        values["url"] = str(data.url)
        config["url_host"] = data.url.host
    if data.kind in ("webhook", "github", "gitlab"):
        if not data.secret:
            generated = secrets.token_urlsafe(32)
        values["signing"] = data.secret or generated or ""
    if data.kind == "email":
        assert data.email is not None
        config["email"] = data.email.model_dump(mode="json")
        values["password"] = data.secret or ""
    if data.kind == "slack_command":
        values["signing"], values["token"] = data.secret or "", data.token or ""
    integration = Integration(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        kind=data.kind,
        name=data.name,
        enabled=data.enabled,
        project_id=data.project_id,
        events=data.events or (DEFAULT_EVENTS if data.kind in OUTBOUND else []),
        config=config,
        secret=_store_secrets(values),
        created_by=ctx.actor.user_id,
    )
    ctx.session.add(integration)
    await ctx.session.flush()
    result = _read(integration)
    events.emit(
        ctx,
        "integration.created",
        "integration",
        integration.id,
        {
            "kind": data.kind,
            "name": data.name,
            "project_id": str(data.project_id) if data.project_id else None,
        },
        project_id=data.project_id,
    )
    return IntegrationCreated(**result.model_dump(), signing_secret=generated)


async def update_integration(
    ctx: ServiceContext, integration_id: uuid.UUID, data: IntegrationUpdate
) -> IntegrationRead:
    i = await _get(ctx, integration_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "events" in changes:
        unknown = set(changes["events"]) - set(EVENT_TYPES)
        if unknown:
            raise InvalidInput(f"unknown event types: {', '.join(sorted(unknown))}")
        i.events = changes["events"]
    if "name" in changes:
        i.name = changes["name"]
    if "enabled" in changes:
        i.enabled = changes["enabled"]
    values = _secrets_of(i)
    config = dict(i.config)
    if data.url is not None:
        if i.kind not in OUTBOUND:
            raise InvalidInput("this integration has no target URL")
        values["url"] = str(data.url)
        config["url_host"] = data.url.host
    if data.secret is not None:
        if not data.secret and i.kind == "slack_command":
            raise InvalidInput("a Slack command needs its signing secret")
        values["password" if i.kind == "email" else "signing"] = data.secret
    if data.token is not None:
        if i.kind != "slack_command":
            raise InvalidInput("only Slack commands have a bot token")
        values["token"] = data.token
    if data.email is not None and i.kind == "email":
        require_org(ctx, Permission.ORG_MANAGE)
        config["email"] = data.email.model_dump(mode="json")
    i.config = config
    i.secret = _store_secrets(values)
    await ctx.session.flush()
    events.emit(
        ctx,
        "integration.updated",
        "integration",
        i.id,
        {"changes": sorted(k for k in changes if k != "secret")},
        project_id=i.project_id,
    )
    return _read(i)


async def delete_integration(ctx: ServiceContext, integration_id: uuid.UUID) -> None:
    i = await _get(ctx, integration_id)
    await ctx.session.delete(i)
    events.emit(
        ctx, "integration.deleted", "integration", integration_id, {"name": i.name}, project_id=i.project_id
    )


async def list_deliveries(
    ctx: ServiceContext, integration_id: uuid.UUID, limit: int = 50
) -> list[DeliveryRead]:
    await _get(ctx, integration_id)
    rows = await ctx.session.scalars(
        select(IntegrationDelivery)
        .where(IntegrationDelivery.integration_id == integration_id)
        .order_by(IntegrationDelivery.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return [DeliveryRead.model_validate(d) for d in rows.all()]


async def test_integration(ctx: ServiceContext, integration_id: uuid.UUID) -> DeliveryRead:
    """Send a test message now (outbound) or check the mailbox login (email)."""
    i = await _get(ctx, integration_id)
    if i.kind == "email":
        from glasshaus.integrations.email import check_login

        error = await check_login(i)
        now = datetime.now(UTC)
        return DeliveryRead(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type="test",
            status="failed" if error else "success",
            attempts=1,
            response_status=None,
            error=error,
            created_at=now,
            delivered_at=None if error else now,
            next_attempt_at=None,
        )
    if i.kind == "slack_command":
        from glasshaus.integrations.slack_command import check_token

        error = await check_token(_secrets_of(i).get("token", ""))
        now = datetime.now(UTC)
        return DeliveryRead(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            event_type="test",
            status="failed" if error else "success",
            attempts=1,
            response_status=None,
            error=error,
            created_at=now,
            delivered_at=None if error else now,
            next_attempt_at=None,
        )
    if i.kind not in OUTBOUND:
        raise InvalidInput("inbound integrations are tested by sending an event from the other system")
    event = {
        "id": str(uuid.uuid4()),
        "type": "integration.test",
        "tenant_id": str(ctx.tenant_id),
        "aggregate_type": "integration",
        "aggregate_id": str(i.id),
        "project_id": None,
        "actor": {
            "user_id": str(ctx.actor.user_id) if ctx.actor.user_id else None,
            "method": ctx.actor.method,
        },
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {},
    }
    from glasshaus.integrations.delivery import render

    payload = await render(ctx.session, i, event)
    delivery = IntegrationDelivery(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        integration_id=i.id,
        event_id=uuid.UUID(str(event["id"])),
        event_type="integration.test",
        status="pending",
        attempts=0,
        payload=payload,
        next_attempt_at=datetime.now(UTC),
    )
    ctx.session.add(delivery)
    await ctx.session.flush()
    from glasshaus.integrations.delivery import attempt

    await attempt(ctx.session, i, delivery)
    return DeliveryRead.model_validate(delivery)


# --------------------------------------------------------------------------- inbound: GitHub / GitLab


def _verify_signature(i: Integration, headers: dict[str, str], body: bytes) -> None:
    secret = _secrets_of(i).get("signing", "")
    if not secret:
        raise Unauthenticated("integration has no signing secret")
    if i.kind == "github":
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, headers.get("x-hub-signature-256", "")):
            raise Unauthenticated("invalid signature")
    else:
        if not hmac.compare_digest(secret, headers.get("x-gitlab-token", "")):
            raise Unauthenticated("invalid token")


def _git_items(kind: str, event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize push / pull request / merge request payloads into linkable items."""
    items: list[dict[str, Any]] = []
    if (kind == "github" and event == "push") or (kind == "gitlab" and event in ("Push Hook", "push")):
        branch = str(payload.get("ref", "")).removeprefix("refs/heads/")
        default = str(
            (payload.get("repository") or {}).get("default_branch")
            or (payload.get("project") or {}).get("default_branch")
            or ""
        )
        for c in (payload.get("commits") or [])[:50]:
            items.append(
                {
                    "kind": "commit",
                    "text": str(c.get("message", "")),
                    "url": str(c.get("url", "")),
                    "label": str(c.get("id", ""))[:8],
                    "author": str((c.get("author") or {}).get("name", "")),
                    "closes": bool(default) and branch == default,
                }
            )
    elif kind == "github" and event == "pull_request":
        pr = payload.get("pull_request") or {}
        action = payload.get("action")
        if action in ("opened", "reopened", "closed", "edited"):
            merged = action == "closed" and bool(pr.get("merged"))
            items.append(
                {
                    "kind": "pull request",
                    "text": "\n".join(
                        [
                            str(pr.get("title", "")),
                            str(pr.get("body") or ""),
                            str((pr.get("head") or {}).get("ref", "")),
                        ]
                    ),
                    "url": str(pr.get("html_url", "")),
                    "label": f"#{pr.get('number')}",
                    "author": str((pr.get("user") or {}).get("login", "")),
                    "state": "merged" if merged else action,
                    "closes": merged,
                }
            )
    elif kind == "gitlab" and event in ("Merge Request Hook", "merge_request"):
        mr = payload.get("object_attributes") or {}
        action = mr.get("action")
        if action in ("open", "reopen", "merge", "close", "update"):
            items.append(
                {
                    "kind": "merge request",
                    "text": "\n".join(
                        [
                            str(mr.get("title", "")),
                            str(mr.get("description") or ""),
                            str(mr.get("source_branch", "")),
                        ]
                    ),
                    "url": str(mr.get("url", "")),
                    "label": f"!{mr.get('iid')}",
                    "author": str((payload.get("user") or {}).get("username", "")),
                    "state": "merged" if action == "merge" else action,
                    "closes": action == "merge",
                }
            )
    return items


async def handle_inbound(
    session: AsyncSession, integration_id: uuid.UUID, headers: dict[str, str], body: bytes
) -> dict[str, Any]:
    """Link commits and pull/merge requests to tasks they mention; 'fixes KEY-12' completes the task
    when merged to the default branch. Returns a summary for the caller."""
    import orjson

    from glasshaus.collab import service as collab
    from glasshaus.collab.schemas import CommentCreate
    from glasshaus.db import apply_tenant, system_session
    from glasshaus.projects.models import Project
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.models import Task

    async with system_session() as lookup:  # the tenant is not known until the integration is found
        tenant_id = await lookup.scalar(select(Integration.tenant_id).where(Integration.id == integration_id))
    if tenant_id is None:
        raise NotFound("integration not found")
    await apply_tenant(session, tenant_id)
    integration = await session.get(Integration, integration_id)
    if integration is None or integration.kind not in ("github", "gitlab") or not integration.enabled:
        raise NotFound("integration not found")
    _verify_signature(integration, headers, body)
    event = headers.get("x-github-event") or headers.get("x-gitlab-event") or ""
    if event == "ping":
        return {"ok": True, "linked": 0}
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise InvalidInput("payload is not JSON") from exc
    project = await session.get(Project, integration.project_id)
    if project is None:
        raise NotFound("integration project not found")
    actor = Actor(
        tenant_id=integration.tenant_id,
        user_id=None,
        org_role=OrgRole.OWNER,
        method="integration",
        client=f"integration:{integration.id}",
    )
    ctx = ServiceContext(session=session, actor=actor)
    linked = closed = 0
    seen: set[tuple[str, str]] = set()
    for item in _git_items(integration.kind, event, payload):
        text = item["text"][:5000]
        refs = {f"{k}-{n}" for k, n in REF.findall(text) if k == project.key}
        closing = {r.upper() for r in CLOSES.findall(text)} & refs if item.get("closes") else set()
        for ref in sorted(refs):
            if (ref, item["url"]) in seen:
                continue
            seen.add((ref, item["url"]))
            task = await session.scalar(
                select(Task).where(
                    Task.project_id == project.id,
                    Task.number == int(ref.split("-")[1]),
                    Task.deleted_at.is_(None),
                )
            )
            if task is None:
                continue
            state = f" ({item['state']})" if item.get("state") else ""
            summary = item["text"].strip().splitlines()[0][:200] if item["text"].strip() else ""
            body_md = (
                f"🔗 Linked {integration.kind.capitalize()} {item['kind']} "
                f"[{item['label']}]({item['url']}){state}"
                f" by {item['author'] or 'unknown'}: {summary}"
            )
            await collab.create_comment(ctx, task.id, CommentCreate(body=body_md))
            linked += 1
            if ref in closing:
                from glasshaus.projects.models import StatusCategory
                from glasshaus.tasks.schemas import TaskUpdate

                done = await tasks._status_in_category(ctx, project.id, StatusCategory.DONE)
                await tasks.update_task(ctx, task.id, TaskUpdate(status_id=done.id))
                closed += 1
    integration.last_success_at = datetime.now(UTC)
    return {"ok": True, "linked": linked, "completed": closed, "events": ctx.pending_events}


# --------------------------------------------------------------------------- calendar feeds


async def get_calendar_feed(ctx: ServiceContext) -> CalendarFeedRead:
    if ctx.actor.user_id is None:
        raise PermissionDenied("calendar feeds belong to people")
    feed = await ctx.session.scalar(select(CalendarFeed).where(CalendarFeed.user_id == ctx.actor.user_id))
    return CalendarFeedRead(
        url=None,
        created_at=feed.created_at if feed else None,
        last_used_at=feed.last_used_at if feed else None,
    )


async def reset_calendar_feed(ctx: ServiceContext) -> CalendarFeedRead:
    """Create (or replace) your private feed URL; the previous URL stops working."""
    if ctx.actor.user_id is None or ctx.actor.method not in ("session", "token", "oauth"):
        raise PermissionDenied("calendar feeds belong to people")
    raw = "ghc_" + secrets.token_urlsafe(32)
    feed = await ctx.session.scalar(select(CalendarFeed).where(CalendarFeed.user_id == ctx.actor.user_id))
    if feed is None:
        feed = CalendarFeed(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant_id,
            user_id=ctx.actor.user_id,
            token_hash=security.sha256(raw),
        )
        ctx.session.add(feed)
    else:
        feed.token_hash = security.sha256(raw)
        feed.created_at = datetime.now(UTC)
        feed.last_used_at = None
    await ctx.session.flush()
    return CalendarFeedRead(
        url=f"{_base()}/api/v1/calendar/{raw}.ics", created_at=feed.created_at, last_used_at=None
    )


async def delete_calendar_feed(ctx: ServiceContext) -> None:
    from sqlalchemy import delete

    await ctx.session.execute(delete(CalendarFeed).where(CalendarFeed.user_id == ctx.actor.user_id))


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    out, data = [], line.encode()
    while len(data) > 75:
        cut = 75
        while cut > 0 and (data[cut] & 0xC0) == 0x80:  # don't split a UTF-8 sequence
            cut -= 1
        out.append(data[:cut].decode())
        data = b" " + data[cut:]
    out.append(data.decode())
    return "\r\n".join(out)


async def calendar_ics(session: AsyncSession, raw: str) -> str:
    """Open tasks assigned to the feed's owner that have dates, as all-day events (next 365 days and
    overdue). Permissions are re-checked as that user on every fetch."""
    from glasshaus.db import apply_tenant
    from glasshaus.identity.models import User
    from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
    from glasshaus.tasks.models import Task

    raw = raw.removesuffix(".ics")
    feed = await session.scalar(select(CalendarFeed).where(CalendarFeed.token_hash == security.sha256(raw)))
    if feed is None:
        raise NotFound("calendar not found")
    await apply_tenant(session, feed.tenant_id)
    user = await session.get(User, feed.user_id)
    if user is None or not user.is_active:
        raise NotFound("calendar not found")
    now = datetime.now(UTC)
    if feed.last_used_at is None or now - feed.last_used_at > timedelta(minutes=10):
        await session.execute(update(CalendarFeed).where(CalendarFeed.id == feed.id).values(last_used_at=now))
    from glasshaus.core.authz import visible_projects_clause

    actor = Actor(tenant_id=feed.tenant_id, user_id=user.id, org_role=user.org_role, method="session")
    ctx = ServiceContext(session=session, actor=actor)
    horizon = date.today() + timedelta(days=365)
    rows = (
        await session.execute(
            select(Task, Project.key, Project.name)
            .join(Project, Project.id == Task.project_id)
            .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            .where(
                Task.assignee_id == user.id,
                Task.deleted_at.is_(None),
                Task.due_date.is_not(None),
                Task.due_date <= horizon,
                ProjectStatus.category.not_in([StatusCategory.DONE, StatusCategory.CANCELLED]),
                visible_projects_clause(ctx),
            )
            .order_by(Task.due_date)
            .limit(2000)
        )
    ).all()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Project Glasshaus//Tasks//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(f'Glasshaus: {user.name}')}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for task, key, project_name in rows:
        due = task.due_date
        assert due is not None  # filtered in the query
        start = task.start_date or due
        end = due + timedelta(days=1)
        ref = f"{key}-{task.number}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{task.id}@glasshaus",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:{_ics_escape(f'{ref} {task.title}'[:250])}",
            f"DESCRIPTION:{_ics_escape(f'{project_name}. Due {due:%Y-%m-%d}.')}",
            f"URL:{_base()}/projects/{key}?task={ref}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


async def count_due_deliveries(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(IntegrationDelivery)
            .where(IntegrationDelivery.status == "pending")
        )
        or 0
    )
