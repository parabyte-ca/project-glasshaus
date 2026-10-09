"""The AI project assistant, phase 1: a daily stand-up digest and a weekly status draft per project.

Each organization has one assistant account ("Project assistant (AI)"). It cannot sign in, is not
listed or provisioned as a person and is never assigned work; a project that turns the assistant on
adds it as a Viewer, so it reads exactly what a viewer would, and everything it does is audited
under its own name. Phase 1 changes nothing: it writes briefs and delivers them.

The facts in a brief (overdue, due, stale, unassigned, completed) are computed here and always go
out. When an organization admin allows the "assistant" AI feature, the model adds a short summary
and focus list (digest) or a written status (weekly draft). Model calls and all delivery (email,
Slack/Teams) happen outside database transactions.
"""

import html
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from glasshaus import mail
from glasshaus.assistant.models import ProjectAssistant, ProjectBrief
from glasshaus.assistant.schemas import (
    AssistantRead,
    AssistantStatus,
    AssistantWrite,
    BriefContent,
    BriefFocus,
    BriefKind,
    BriefRead,
    BriefSummary,
    BriefTask,
    ChannelOption,
    DeliverySettings,
    DigestSettings,
    WeeklySettings,
)
from glasshaus.automation.schedule import next_occurrence
from glasshaus.automation.schemas import Frequency, ScheduleSpec
from glasshaus.config import get_settings
from glasshaus.core import events
from glasshaus.core.authz import project_role, require_project
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, RateLimited, ServiceError
from glasshaus.core.rbac import OrgRole, Permission, ProjectRole, WorkspaceRole
from glasshaus.db import system_session, unit_of_work
from glasshaus.identity.models import ASSISTANT_KIND, User, WorkspaceMember
from glasshaus.logs import get_logger
from glasshaus.projects.models import Project, ProjectMember, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Task

log = get_logger(__name__)

ACCOUNT_EMAIL = "project-assistant@glasshaus.invalid"
ACCOUNT_NAME = "Project assistant (AI)"
CHANNELS = ("slack", "teams")
OPEN = (StatusCategory.BACKLOG, StatusCategory.TODO, StatusCategory.IN_PROGRESS)
LIST_LIMIT = 20
KEEP_DAYS = 180
RUN_NOW_PER_MINUTE = 3
CHANGE_IT = "Project admins change this on the project's Assistant page."
HEALTH = {"on_track": "On track", "at_risk": "At risk", "off_track": "Off track"}


# --------------------------------------------------------------------------- the AI account


async def ensure_account(ctx: ServiceContext) -> User:
    """The organization's assistant account, created on first use."""
    user = await ctx.session.scalar(select(User).where(User.kind == ASSISTANT_KIND))
    if user is None:
        await ctx.session.execute(
            insert(User)
            .values(
                id=uuid.uuid4(),
                tenant_id=ctx.tenant_id,
                email=ACCOUNT_EMAIL,
                name=ACCOUNT_NAME,
                org_role=OrgRole.GUEST,
                password_hash=None,
                kind=ASSISTANT_KIND,
                is_active=True,
            )
            .on_conflict_do_nothing()
        )
        user = await ctx.session.scalar(select(User).where(User.kind == ASSISTANT_KIND))
        if user is None:  # an ordinary account already uses the address: refuse rather than reuse it
            raise InvalidInput(f"{ACCOUNT_EMAIL} belongs to another account; rename it first")
    return user


def _account_actor(tenant_id: uuid.UUID, account_id: uuid.UUID) -> Actor:
    return Actor(tenant_id=tenant_id, user_id=account_id, org_role=OrgRole.GUEST, method="system")


async def _join(ctx: ServiceContext, project_id: uuid.UUID, account: User) -> None:
    """Make the assistant a Viewer of the project (and nothing more)."""
    await ctx.session.execute(
        insert(ProjectMember)
        .values(tenant_id=ctx.tenant_id, project_id=project_id, user_id=account.id, role=ProjectRole.VIEWER)
        .on_conflict_do_update(index_elements=["project_id", "user_id"], set_={"role": ProjectRole.VIEWER})
    )


async def _leave(ctx: ServiceContext, project_id: uuid.UUID, account_id: uuid.UUID) -> None:
    await ctx.session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == account_id
        )
    )


# --------------------------------------------------------------------------- schedule


def next_digest(a: ProjectAssistant, after: datetime) -> datetime | None:
    if not (a.enabled and a.digest_enabled):
        return None
    spec = ScheduleSpec(
        frequency=Frequency.DAILY, hour=a.digest_hour, minute=a.digest_minute, timezone=a.timezone
    )
    at = next_occurrence(spec, after)
    while a.weekdays_only and at.astimezone(ZoneInfo(a.timezone)).weekday() >= 5:
        at = next_occurrence(spec, at)
    return at


def next_weekly(a: ProjectAssistant, after: datetime) -> datetime | None:
    if not (a.enabled and a.weekly_enabled):
        return None
    spec = ScheduleSpec(
        frequency=Frequency.WEEKLY, weekday=a.weekly_weekday, hour=a.weekly_hour, timezone=a.timezone
    )
    return next_occurrence(spec, after)


# --------------------------------------------------------------------------- settings


def _read(a: ProjectAssistant) -> AssistantRead:
    return AssistantRead(
        project_id=a.project_id,
        enabled=a.enabled,
        timezone=a.timezone,
        digest=DigestSettings(
            enabled=a.digest_enabled,
            hour=a.digest_hour,
            minute=a.digest_minute,
            weekdays_only=a.weekdays_only,
        ),
        weekly=WeeklySettings(enabled=a.weekly_enabled, weekday=a.weekly_weekday, hour=a.weekly_hour),
        stale_days=a.stale_days,
        suggestions=a.suggest,
        trusted=list(a.trusted),
        auto_daily_cap=a.auto_daily_cap,
        delivery=DeliverySettings(in_app=a.notify_in_app, email=a.notify_email, channel_id=a.channel_id),
        next_digest_at=a.next_digest_at,
        next_weekly_at=a.next_weekly_at,
        last_run_at=a.last_run_at,
        last_error=a.last_error,
    )


async def _settings(ctx: ServiceContext, project_id: uuid.UUID) -> ProjectAssistant | None:
    return await ctx.session.scalar(select(ProjectAssistant).where(ProjectAssistant.project_id == project_id))


async def _can_manage(ctx: ServiceContext, project: Project) -> bool:
    role = await project_role(ctx, project)
    return role == ProjectRole.ADMIN and ctx.actor.user_id is not None


async def _channels(ctx: ServiceContext, project_id: uuid.UUID) -> list[ChannelOption]:
    """Slack/Teams integrations this person may point the assistant at."""
    from glasshaus.integrations.models import Integration

    where = Integration.project_id == project_id
    if ctx.actor.is_org_admin:
        where = where | Integration.project_id.is_(None)
    rows = await ctx.session.scalars(
        select(Integration)
        .where(Integration.kind.in_(CHANNELS), where)
        .order_by(func.lower(Integration.name))
    )
    return [ChannelOption(id=i.id, name=i.name, kind=i.kind) for i in rows.all()]


async def _trusted_allowed(ctx: ServiceContext) -> list[Any]:
    from glasshaus.governance.models import OrgSettings

    org = await ctx.session.get(OrgSettings, ctx.tenant_id)
    return sorted(org.assistant_trusted) if org else []


async def ai_allowed(ctx: ServiceContext) -> bool:
    from glasshaus.ai import service as ai

    return "assistant" in (await ai.get_status(ctx)).features


async def get_status(ctx: ServiceContext, project_id: uuid.UUID) -> AssistantStatus:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    manage = await _can_manage(ctx, project)
    a = await _settings(ctx, project_id)
    from glasshaus.assistant import suggestions

    return AssistantStatus(
        settings=_read(a) if a else None,
        account_name=ACCOUNT_NAME,
        can_manage=manage,
        can_approve=await suggestions.can_approve(ctx, project),
        trusted_allowed=await _trusted_allowed(ctx),
        ai=await ai_allowed(ctx),
        email_available=mail.available(),
        channels=await _channels(ctx, project_id) if manage else [],
    )


async def configure(ctx: ServiceContext, project_id: uuid.UUID, data: AssistantWrite) -> AssistantRead:
    """Turn the assistant on (or change it) for a project. Project admins only."""
    project = await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    if ctx.actor.user_id is None:
        raise InvalidInput("the project assistant is set up by a person; sign in as one")
    if data.delivery.channel_id is not None and data.delivery.channel_id not in {
        c.id for c in await _channels(ctx, project_id)
    }:
        raise InvalidInput("pick a Slack or Teams integration of this project")
    account = await ensure_account(ctx)
    a = await _settings(ctx, project_id)
    if a is None:
        a = ProjectAssistant(tenant_id=ctx.tenant_id, project_id=project_id)
        ctx.session.add(a)
    a.enabled, a.timezone, a.stale_days = data.enabled, data.timezone, data.stale_days
    a.digest_enabled, a.digest_hour, a.digest_minute = (
        data.digest.enabled,
        data.digest.hour,
        data.digest.minute,
    )
    a.weekdays_only = data.digest.weekdays_only
    a.weekly_enabled, a.weekly_weekday, a.weekly_hour = (
        data.weekly.enabled,
        data.weekly.weekday,
        data.weekly.hour,
    )
    a.notify_in_app, a.notify_email = data.delivery.in_app, data.delivery.email
    a.channel_id = data.delivery.channel_id
    a.suggest = data.suggestions
    allowed = await _trusted_allowed(ctx)
    if not set(data.trusted) <= set(allowed):
        raise InvalidInput(
            "your organization does not allow the assistant to do that without approval "
            "(Admin > AI assistant)"
        )
    a.trusted, a.auto_daily_cap = sorted(set(data.trusted)), data.auto_daily_cap
    a.configured_by = ctx.actor.user_id
    now = datetime.now(UTC)
    a.next_digest_at, a.next_weekly_at = next_digest(a, now), next_weekly(a, now)
    a.last_error = None
    if a.enabled:
        await _join(ctx, project.id, account)
    else:
        await _leave(ctx, project.id, account.id)
    await ctx.session.flush()
    result = _read(a)
    events.emit(ctx, "project.assistant_set", "project", project.id, result)
    return result


async def remove(ctx: ServiceContext, project_id: uuid.UUID) -> None:
    """Turn the assistant off and forget its settings. Briefs already written are kept."""
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    a = await _settings(ctx, project_id)
    if a is None:
        raise NotFound("the assistant is not set up for this project")
    account = await ctx.session.scalar(select(User).where(User.kind == ASSISTANT_KIND))
    if account is not None:
        await _leave(ctx, project_id, account.id)
    await ctx.session.delete(a)
    await ctx.session.flush()
    events.emit(ctx, "project.assistant_removed", "project", project_id, {"project_id": str(project_id)})


# --------------------------------------------------------------------------- briefs (reading)


def _brief(b: ProjectBrief, key: str) -> BriefRead:
    return BriefRead(
        id=b.id,
        kind=b.kind,
        title=b.title,
        created_at=b.created_at,
        project_id=b.project_id,
        project_key=key,
        content=BriefContent.model_validate(b.content),
    )


async def list_briefs(
    ctx: ServiceContext, project_id: uuid.UUID, *, kind: BriefKind | None = None, limit: int = 30
) -> list[BriefSummary]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    stmt = select(ProjectBrief).where(ProjectBrief.project_id == project_id)
    if kind:
        stmt = stmt.where(ProjectBrief.kind == kind)
    rows = await ctx.session.scalars(
        stmt.order_by(ProjectBrief.created_at.desc()).limit(min(max(limit, 1), 100))
    )
    return [BriefSummary(id=b.id, kind=b.kind, title=b.title, created_at=b.created_at) for b in rows.all()]


async def get_brief(ctx: ServiceContext, brief_id: uuid.UUID) -> BriefRead:
    b = await ctx.session.get(ProjectBrief, brief_id)
    if b is None:
        raise NotFound("brief not found")
    project = await require_project(ctx, b.project_id, Permission.PROJECT_READ)
    return _brief(b, project.key)


async def latest_brief(ctx: ServiceContext, project_id: uuid.UUID, kind: BriefKind) -> BriefRead | None:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    b = await ctx.session.scalar(
        select(ProjectBrief)
        .where(ProjectBrief.project_id == project_id, ProjectBrief.kind == kind)
        .order_by(ProjectBrief.created_at.desc())
        .limit(1)
    )
    return _brief(b, project.key) if b else None


# --------------------------------------------------------------------------- facts


async def _facts(
    ctx: ServiceContext, project_id: uuid.UUID, kind: BriefKind, *, tz: str, stale_days: int
) -> tuple[Project, BriefContent]:
    """Everything a brief states, read with the caller's (the assistant's) access."""
    from glasshaus.insights import service as insights
    from glasshaus.scheduling import service as scheduling

    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo(tz)).date()
    previous = await ctx.session.scalar(
        select(func.max(ProjectBrief.created_at)).where(
            ProjectBrief.project_id == project_id, ProjectBrief.kind == kind
        )
    )
    window = timedelta(days=1 if kind == "digest" else 7)
    since = max(previous, now - 3 * window) if previous else now - window
    soon = today + timedelta(days=3 if kind == "digest" else 7)
    rows = (
        await ctx.session.execute(
            select(Task, ProjectStatus)
            .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            .where(Task.project_id == project_id, Task.deleted_at.is_(None))
        )
    ).all()
    people = {t.assignee_id for t, _ in rows if t.assignee_id}
    names: dict[uuid.UUID, str] = {}
    if people:
        found = await ctx.session.execute(select(User.id, User.name).where(User.id.in_(people)))
        names = dict(found.all())

    def item(t: Task, s: ProjectStatus, days: int | None = None) -> BriefTask:
        return BriefTask(
            key=f"{project.key}-{t.number}",
            title=t.title,
            status=s.name,
            assignee=names.get(t.assignee_id) if t.assignee_id else None,
            due_date=t.due_date,
            days=days,
        )

    open_rows = [(t, s) for t, s in rows if s.category in OPEN]
    by_due = sorted((r for r in open_rows if r[0].due_date), key=lambda r: (r[0].due_date, r[0].number))
    completed = sorted(
        (
            (t, s)
            for t, s in rows
            if s.category == StatusCategory.DONE and t.completed_at and t.completed_at >= since
        ),
        key=lambda r: r[0].completed_at or now,
        reverse=True,
    )
    stale_before = now - timedelta(days=stale_days)
    stale = sorted(
        (
            (t, s)
            for t, s in open_rows
            if s.category == StatusCategory.IN_PROGRESS and t.updated_at < stale_before
        ),
        key=lambda r: r[0].updated_at,
    )
    health = await insights.project_health(ctx, project)
    warnings = [w.message for w in await scheduling.schedule_warnings(ctx, project_id, today=today)]
    content = BriefContent(
        date=today,
        since=since,
        health=health.health,
        progress=round(health.progress * 100),
        open=len(open_rows),
        done=health.done,
        overdue=sum(1 for t, _ in by_due if t.due_date and t.due_date < today),
        completed=[item(t, s) for t, s in completed[:LIST_LIMIT]],
        overdue_tasks=[
            item(t, s, (today - t.due_date).days) for t, s in by_due if t.due_date and t.due_date < today
        ][:LIST_LIMIT],
        due_today=[item(t, s) for t, s in by_due if t.due_date == today][:LIST_LIMIT],
        due_soon=[item(t, s) for t, s in by_due if t.due_date and today < t.due_date <= soon][:LIST_LIMIT],
        stale=[item(t, s, (now - t.updated_at).days) for t, s in stale[:LIST_LIMIT]],
        unassigned=[
            item(t, s) for t, s in by_due if t.assignee_id is None and t.due_date and t.due_date <= soon
        ][:LIST_LIMIT],
        warnings=warnings[:10],
        stale_days=stale_days,
    )
    return project, content


def _title(kind: BriefKind, key: str, c: BriefContent) -> str:
    if kind == "weekly":
        return f"{key} weekly status draft, week of {c.date - timedelta(days=c.date.weekday()):%b %-d}"
    parts = [f"{c.overdue} overdue", f"{len(c.due_today)} due today"]
    if c.stale:
        parts.append(f"{len(c.stale)} stale")
    return f"{key} stand-up, {c.date:%a %b %-d}: " + ", ".join(parts)


# --------------------------------------------------------------------------- AI write-up


class _Focus(BaseModel):
    text: str = Field(description="One short, concrete suggestion for today.")
    task_key: str | None = Field(description="The task it is about, if any (a key from the data).")


class DigestOutput(BaseModel):
    summary: str = Field(description="Two to four sentences: where the project stands today.")
    focus: list[_Focus] = Field(
        description="At most 5 things the team should look at today, most important first."
    )


class WeeklyOutput(BaseModel):
    headline: str = Field(description="One sentence on overall status.")
    summary: str = Field(description="Two or three short paragraphs of Markdown for a status update.")
    highlights: list[str] = Field(description="Notable completed work, at most 5 bullets.")
    concerns: list[str] = Field(description="Problems needing attention, at most 5 bullets.")


def _payload(key: str, name: str, c: BriefContent) -> dict[str, Any]:
    def tasks(items: list[BriefTask]) -> list[dict[str, Any]]:
        return [
            {
                "key": t.key,
                "title": t.title,
                "status": t.status,
                "assignee": t.assignee,
                "due": t.due_date.isoformat() if t.due_date else None,
                **({"days": t.days} if t.days is not None else {}),
            }
            for t in items
        ]

    return {
        "project": {"key": key, "name": name},
        "today": c.date.isoformat(),
        "health": {"status": c.health, "progress_percent": c.progress, "open": c.open, "done": c.done},
        "completed_recently": tasks(c.completed),
        "overdue": tasks(c.overdue_tasks),
        "due_today": tasks(c.due_today),
        "due_soon": tasks(c.due_soon),
        f"in_progress_without_update_for_{c.stale_days}_days_or_more": tasks(c.stale),
        "unassigned_and_due_soon": tasks(c.unassigned),
        "schedule_warnings": c.warnings,
    }


async def _write_up(actor: Actor, kind: BriefKind, key: str, name: str, c: BriefContent) -> None:
    """Add the AI part to ``c`` in place; on any failure say why and keep the facts."""
    from glasshaus.ai import service as ai

    data = ai._data(_payload(key, name, c))
    lists = (c.completed, c.overdue_tasks, c.due_today, c.due_soon, c.stale, c.unassigned)
    known = {t.key for items in lists for t in items}
    try:
        if kind == "digest":
            out, usage = await ai._run(
                actor,
                "assistant",
                key,
                system=(
                    "You are the project assistant: a careful junior project manager writing the team's "
                    "morning stand-up digest. Be brief and specific, name owners when known, and only "
                    "suggest what the data supports. " + ai.GUARD
                ),
                prompt=f"Write today's stand-up digest from this data.\n\n{data}",
                output=DigestOutput,
                max_tokens=3000,
            )
            c.summary = out.summary.strip()[:2000]
            c.focus = [
                BriefFocus(
                    text=f.text.strip()[:300],
                    task_key=f.task_key.upper() if f.task_key and f.task_key.upper() in known else None,
                )
                for f in out.focus[:5]
                if f.text.strip()
            ]
        else:
            weekly, usage = await ai._run(
                actor,
                "assistant",
                key,
                system=(
                    "You are the project assistant drafting the weekly status update for the project's "
                    "admins to edit and send. Lead with the outcome, mention blockers and dates, and do "
                    "not invent facts. " + ai.GUARD
                ),
                prompt=f"Draft this week's status update from this data.\n\n{data}",
                output=WeeklyOutput,
                max_tokens=4000,
            )
            c.headline = weekly.headline.strip()[:300]
            c.summary = weekly.summary.strip()[:6000]
            c.highlights = [h.strip()[:300] for h in weekly.highlights[:5] if h.strip()]
            c.concerns = [h.strip()[:300] for h in weekly.concerns[:5] if h.strip()]
        c.ai_model = usage.model
    except ServiceError as exc:
        c.ai_note = f"No AI write-up this time: {exc}"
    except Exception:  # never lose the facts because the model failed
        log.exception("assistant.ai_failed", project=key)
        c.ai_note = "No AI write-up this time: the AI request failed"


# --------------------------------------------------------------------------- writing a brief


async def _account_for(tenant_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    """The assistant account's id, joined to the project (re-added if someone removed it)."""
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        account = await ensure_account(ctx)
        await _join(ctx, project_id, account)
        return account.id


async def write_brief(
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    kind: BriefKind,
    *,
    tz: str,
    stale_days: int,
    suggest: bool = False,
) -> BriefRead:
    """Gather the facts as the assistant, add the AI write-up if allowed, and store the brief. A
    digest also refreshes the approval queue when the project asks for suggestions."""
    from glasshaus.assistant import suggestions

    account = await _account_for(tenant_id, project_id)
    actor = _account_actor(tenant_id, account)
    async with unit_of_work(actor) as ctx:
        project, content = await _facts(ctx, project_id, kind, tz=tz, stale_days=stale_days)
        key, name = project.key, project.name
        use_ai = await ai_allowed(ctx)
    if use_ai:
        await _write_up(actor, kind, key, name, content)
    else:
        content.ai_note = "AI write-ups are off for this organization (Admin > AI assistant)"
    if kind == "digest" and suggest:
        try:
            content.suggestions = await suggestions.refresh(
                tenant_id, project_id, tz=tz, stale_days=stale_days
            )
        except Exception:  # the digest goes out even if suggesting fails
            log.exception("assistant.suggest_failed", project=key)
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        brief = ProjectBrief(
            tenant_id=tenant_id,
            project_id=project_id,
            kind=kind,
            title=_title(kind, key, content),
            content=content.model_dump(mode="json"),
        )
        ctx.session.add(brief)
        await ctx.session.execute(
            delete(ProjectBrief).where(
                ProjectBrief.project_id == project_id,
                ProjectBrief.created_at < datetime.now(UTC) - timedelta(days=KEEP_DAYS),
            )
        )
        await ctx.session.flush()
        return _brief(brief, key)


async def _limit_run_now(actor: Actor) -> None:
    from glasshaus.redis_client import get_redis

    key = f"glasshaus:assistant:rl:{actor.tenant_id}:{actor.user_id}:{int(time.time() // 60)}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 90)
    except Exception:
        log.warning("assistant.rate_limit_unavailable", exc_info=True)
        return
    if count > RUN_NOW_PER_MINUTE:
        raise RateLimited("too many assistant runs this minute; try again shortly")


async def run_now(actor: Actor, project_id: uuid.UUID, kind: BriefKind) -> BriefRead:
    """Write a brief now (project admins). It is stored on the project; nobody is notified."""
    async with unit_of_work(actor) as ctx:
        await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
        if actor.user_id is None:
            raise InvalidInput("sign in as a person to run the assistant")
        a = await _settings(ctx, project_id)
        if a is None or not a.enabled:
            raise InvalidInput("turn the assistant on for this project first")
        tz, stale_days, suggest = a.timezone, a.stale_days, a.suggest
    await _limit_run_now(actor)
    return await write_brief(actor.tenant_id, project_id, kind, tz=tz, stale_days=stale_days, suggest=suggest)


# --------------------------------------------------------------------------- delivery


async def recipients(
    ctx: ServiceContext, project: Project, kind: BriefKind
) -> list[tuple[uuid.UUID, str, str]]:
    """(id, name, email) of active people on the project: everyone for the digest, admins for the draft."""
    explicit = (
        await ctx.session.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(ProjectMember.project_id == project.id)
        )
    ).all()
    via_ws = (
        await ctx.session.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == project.workspace_id
            )
        )
    ).all()
    if kind == "weekly":
        ids = {u for u, r in explicit if r == ProjectRole.ADMIN} | {
            u for u, r in via_ws if r == WorkspaceRole.ADMIN
        }
    else:
        ids = {u for u, _ in explicit} | {u for u, _ in via_ws}
    if not ids:
        return []
    rows = await ctx.session.execute(
        select(User.id, User.name, User.email)
        .where(User.id.in_(ids), User.is_active.is_(True), User.kind != ASSISTANT_KIND)
        .order_by(func.lower(User.name))
    )
    return [(r.id, r.name, r.email) for r in rows.all()]


def _url(path: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}{path}"


def brief_link(b: BriefRead) -> str:
    return f"/projects/{b.project_key}/assistant?brief={b.id}"


def _sections(c: BriefContent, kind: BriefKind) -> list[tuple[str, list[str]]]:
    def line(t: BriefTask, extra: str = "") -> str:
        who = f" ({t.assignee})" if t.assignee else ""
        return f"{t.key} {t.title}{who}{extra}"

    def days(n: int) -> str:
        return f"{n} day" + ("" if n == 1 else "s")

    sections = [
        ("Overdue", [line(t, f", {days(t.days or 0)} late") for t in c.overdue_tasks]),
        ("Due today", [line(t) for t in c.due_today]),
        ("Due soon", [line(t, f", due {t.due_date:%b %-d}" if t.due_date else "") for t in c.due_soon]),
        (f"No update for {c.stale_days}+ days", [line(t, f", {days(t.days or 0)}") for t in c.stale]),
        ("Unassigned and due soon", [line(t) for t in c.unassigned]),
        ("Completed" if kind == "weekly" else "Done since the last digest", [line(t) for t in c.completed]),
        ("Schedule warnings", list(c.warnings)),
        (
            "Waiting for approval",
            [f"{c.suggestions} suggestion{'s' if c.suggestions != 1 else ''} on the Digests page"]
            if c.suggestions and kind == "digest"
            else [],
        ),
    ]
    return [(h, items) for h, items in sections if items]


def _numbers(c: BriefContent) -> str:
    return f"{HEALTH.get(c.health, c.health)} · {c.progress}% complete · Open {c.open} · Overdue {c.overdue}"


def build_mail(to: str, b: BriefRead) -> mail.Mail:
    """Plain text and escaped HTML of a brief."""
    c, link = b.content, _url(brief_link(b))
    lines = [b.title, _numbers(c), ""]
    if c.headline:
        lines += [c.headline, ""]
    if c.summary:
        lines += [c.summary, ""]
    if c.focus:
        lines += ["Focus today", *(f"- {f.text}" for f in c.focus), ""]
    for heading, items in (("Highlights", c.highlights), ("Concerns", c.concerns)):
        if items:
            lines += [heading, *(f"- {x}" for x in items), ""]
    for heading, items in _sections(c, b.kind):
        lines += [heading, *(f"- {x}" for x in items[:10]), ""]
    footer = (
        "Written by the project assistant (AI). Check before acting; it can be wrong."
        if c.ai_model
        else "Written by the project assistant."
    )
    lines += [f"Open in Glasshaus: {link}", "", footer, CHANGE_IT]

    e = html.escape
    p = 'style="margin:0 0 8px"'
    parts = [
        '<div style="font-family:Inter,Segoe UI,Arial,sans-serif;color:#212121;font-size:14px">',
        f'<h1 style="font-size:18px;margin:0 0 4px">{e(b.title)}</h1>',
        f'<p style="margin:0 0 12px;color:#525252">{e(_numbers(c))}</p>',
    ]
    if c.headline:
        parts.append(f"<p {p}><strong>{e(c.headline)}</strong></p>")
    if c.summary:
        parts += [f"<p {p}>{e(x)}</p>" for x in c.summary.split("\n\n") if x.strip()]
    blocks: list[tuple[str, list[str]]] = []
    if c.focus:
        blocks.append(("Focus today", [f.text for f in c.focus]))
    blocks += [(h, x) for h, x in (("Highlights", c.highlights), ("Concerns", c.concerns)) if x]
    blocks += [(h, x[:10]) for h, x in _sections(c, b.kind)]
    for heading, items in blocks:
        parts.append(f'<h2 style="font-size:15px;margin:12px 0 4px">{e(heading)}</h2>')
        bullets = "".join(f"<li>{e(x)}</li>" for x in items)
        parts.append(f'<ul style="margin:0;padding-left:20px">{bullets}</ul>')
    anchor = f'<a href="{e(link)}" style="color:#1c75bc">Open in Glasshaus</a>'
    parts.append(f'<p style="margin-top:16px">{anchor}</p>')
    parts.append(f'<p style="font-size:12px;color:#525252">{e(footer)}</p></div>')
    return mail.Mail(to=to, subject=b.title, text="\n".join(lines), html="".join(parts))


def render_channel(kind: str, b: BriefRead) -> dict[str, Any]:
    """A Slack message or Teams card for a digest."""
    from glasshaus.integrations.posts import _clip, _slack, _teams

    c, link = b.content, _url(brief_link(b))
    sections = [(h, [_clip(x, 120) for x in items[:5]]) for h, items in _sections(c, b.kind)]
    if c.focus:
        sections.insert(0, ("Focus today", [_clip(f.text, 160) for f in c.focus]))
    summary = _clip(c.summary, 600) if c.summary else ""
    if kind == "slack":
        text = [f"*{_slack(b.title)}*", _numbers(c)]
        if summary:
            text.append(_slack(summary))
        for heading, items in sections:
            text.append(f"*{_slack(heading)}*\n" + "\n".join(f"• {_slack(x)}" for x in items))
        return {
            "text": b.title,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(text)[:2900]}},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"<{link}|Open in Glasshaus> · Written by the project assistant",
                        }
                    ],
                },
            ],
            "unfurl_links": False,
        }
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": b.title, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": _numbers(c), "isSubtle": True, "spacing": "None", "wrap": True},
    ]
    if summary:
        body.append({"type": "TextBlock", "text": summary, "wrap": True})
    for heading, items in sections:
        body.append({"type": "TextBlock", "text": heading, "weight": "Bolder", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": "\n".join(f"- {x}" for x in items), "wrap": True})
    return _teams(b.title, body, link)


async def _post_channel(tenant_id: uuid.UUID, integration_id: uuid.UUID, b: BriefRead) -> str | None:
    """Queue and send the digest to Slack/Teams. Returns an error message, or None."""
    from glasshaus.integrations.delivery import _outgoing, _send_all
    from glasshaus.integrations.models import Integration, IntegrationDelivery

    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        i = await ctx.session.get(Integration, integration_id)
        if i is None or i.kind not in CHANNELS or i.project_id not in (None, b.project_id):
            return "the Slack/Teams integration is gone"
        if not i.enabled:
            return "the Slack/Teams integration is turned off"
        delivery = IntegrationDelivery(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            integration_id=i.id,
            event_id=b.id,
            event_type=f"assistant.{b.kind}",
            status="pending",
            attempts=0,
            payload=render_channel(i.kind, b),
            next_attempt_at=datetime.now(UTC),
        )
        ctx.session.add(delivery)
        await ctx.session.flush()
        outgoing, delivery_id = _outgoing(i, delivery), delivery.id
    await _send_all([outgoing])  # failures retry on the delivery cron
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        sent = await ctx.session.get(IntegrationDelivery, delivery_id)
        if sent is not None and sent.status != "success":
            return (sent.error or "not delivered yet; retrying")[:200]
    return None


async def deliver(tenant_id: uuid.UUID, assistant_id: uuid.UUID, b: BriefRead) -> list[str]:
    """Send a brief the way the project asked. Returns the problems met (empty when all went out)."""
    from glasshaus.collab.models import NotificationKind
    from glasshaus.collab.service import notify_users

    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        a = await ctx.session.get(ProjectAssistant, assistant_id)
        project = await ctx.session.get(Project, b.project_id)
        if a is None or project is None:
            return []
        people = await recipients(ctx, project, b.kind)
        in_app, email, channel = a.notify_in_app, a.notify_email, a.channel_id
        if in_app and people:
            await notify_users(
                ctx,
                [p[0] for p in people],
                kind=NotificationKind.ASSISTANT,
                title=b.title,
                link=brief_link(b),
                event_id=b.id,
            )
    problems: list[str] = []
    if email and people:
        if not mail.available():
            problems.append("email is not configured on this server")
        else:
            failed = 0
            for _, _, address in people:
                try:
                    await mail.send(build_mail(address, b))
                except ServiceError:
                    failed += 1
            if failed:
                problems.append(f"{failed} of {len(people)} emails could not be sent")
    if channel and b.kind == "digest" and (error := await _post_channel(tenant_id, channel, b)):
        problems.append(error)
    return problems


# --------------------------------------------------------------------------- worker


async def _run_scheduled(tenant_id: uuid.UUID, assistant_id: uuid.UUID, kind: BriefKind) -> bool:
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        a = await ctx.session.get(ProjectAssistant, assistant_id)
        if a is None or not a.enabled:
            return False
        project = await ctx.session.get(Project, a.project_id)
        if project is None or project.archived_at is not None:
            return False
        project_id, tz, stale_days, suggest = a.project_id, a.timezone, a.stale_days, a.suggest
    error: str | None = None
    try:
        brief = await write_brief(tenant_id, project_id, kind, tz=tz, stale_days=stale_days, suggest=suggest)
        problems = await deliver(tenant_id, assistant_id, brief)
        error = "; ".join(problems) or None
    except ServiceError as exc:
        error = str(exc)
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        a = await ctx.session.get(ProjectAssistant, assistant_id)
        if a is not None:
            a.last_run_at, a.last_error = datetime.now(UTC), (error[:300] if error else None)
    if error:
        log.warning("assistant.run_problem", assistant=str(assistant_id), kind=kind, error=error)
    return error is None


async def run_due(now: datetime | None = None, *, batch: int = 50) -> dict[str, int]:
    """Worker job: write and deliver every digest and weekly draft that is due."""
    now = now or datetime.now(UTC)
    due: list[tuple[uuid.UUID, uuid.UUID, BriefKind]] = []
    async with system_session() as session:
        rows = (
            await session.scalars(
                select(ProjectAssistant)
                .where(
                    ProjectAssistant.enabled.is_(True),
                    (ProjectAssistant.next_digest_at <= now) | (ProjectAssistant.next_weekly_at <= now),
                )
                .order_by(func.least(ProjectAssistant.next_digest_at, ProjectAssistant.next_weekly_at))
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for a in rows:
            # Move on first, so a failing project is retried at its next time, not every minute.
            if a.next_digest_at and a.next_digest_at <= now:
                a.next_digest_at = next_digest(a, now)
                due.append((a.tenant_id, a.id, "digest"))
            if a.next_weekly_at and a.next_weekly_at <= now:
                a.next_weekly_at = next_weekly(a, now)
                due.append((a.tenant_id, a.id, "weekly"))
    ok = 0
    for tenant_id, assistant_id, kind in due:
        try:
            ok += await _run_scheduled(tenant_id, assistant_id, kind)
        except Exception:  # one broken project must not stop the others
            log.exception("assistant.error", assistant=str(assistant_id), kind=kind)
    return {"written": len(due), "ok": ok}
