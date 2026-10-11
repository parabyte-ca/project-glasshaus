"""The project assistant, phase 2: an approval queue.

With each daily digest the assistant proposes follow-up comments (stale or overdue work), new due
dates (long-overdue work that has not started) and owners (unassigned work due soon). People can also
paste meeting notes or an email to get proposed tasks. Simple rules make the proposals; when the
organization allows AI write-ups, the model makes better ones (validated against the project's data).

Nothing changes until a project editor or admin approves a suggestion, optionally editing it first.
The change is then made by the assistant account, with "approved by <name>" on what it writes, and
the approval is audited under the approver's name. A suggestion whose task changed since it was made
(another due date or owner, done, deleted) is marked stale instead of being applied.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from glasshaus.assistant.models import AssistantSuggestion
from glasshaus.assistant.schemas import (
    NewTask,
    SuggestionDecision,
    SuggestionRead,
    SuggestionTask,
)
from glasshaus.audit import service as audit
from glasshaus.core.authz import project_role, require_project
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound, ServiceError
from glasshaus.core.rbac import OrgRole, Permission, ProjectRole, WorkspaceRole
from glasshaus.db import unit_of_work
from glasshaus.identity.models import ASSISTANT_KIND, User, WorkspaceMember
from glasshaus.logs import get_logger
from glasshaus.projects.models import Project, ProjectMember, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Task

log = get_logger(__name__)

OPEN = (StatusCategory.BACKLOG, StatusCategory.TODO, StatusCategory.IN_PROGRESS)
NOT_STARTED = (StatusCategory.BACKLOG, StatusCategory.TODO)
MAX_NEW_PER_RUN = 10
MAX_OPEN = 30
MAX_OPEN_NOTES = 50  # tasks proposed from notes wait for a person; this many at most
EXPIRE_DAYS = 7
QUIET_DAYS = 7  # after a decision, the same suggestion is not made again for this long
MAX_NOTE_TASKS = 15
NOTE_LINE = re.compile(r"^\s*(?:[-*]\s*\[\s?\]|todo\s*:|action(?:\s+item)?\s*:|ai\s*:)\s*(.+)$", re.I)


@dataclass
class OpenTask:
    id: uuid.UUID
    key: str
    title: str
    category: StatusCategory
    status: str
    assignee_id: uuid.UUID | None
    assignee: str | None
    due_date: date | None
    start_date: date | None
    updated_at: datetime


@dataclass
class Person:
    id: uuid.UUID
    name: str
    open: int


@dataclass
class Draft:
    kind: str
    source: str
    reason: str
    data: dict[str, Any]
    task_id: uuid.UUID | None = None
    dedupe_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _by_name(people: list[Person]) -> dict[str, Person]:
    """People by lower-case name, leaving out names two people share (the model could mean either)."""
    seen: dict[str, list[Person]] = {}
    for p in people:
        seen.setdefault(p.name.strip().lower(), []).append(p)
    return {name: group[0] for name, group in seen.items() if len(group) == 1}


def _mention(user_id: uuid.UUID, name: str) -> str:
    return f"@[{name}](user:{user_id})"


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"<?\b(?:https?|ftp|mailto|javascript|data):[^\s>)\]]*>?", re.IGNORECASE)
_WWW = re.compile(r"\bwww\.[^\s)\]]+", re.IGNORECASE)


def defang(text: str) -> str:
    """Model-written text is plain words: it must not mention anyone by itself (neutralise @ tokens
    and @emails) or carry links or images, which injected task text could otherwise slip in."""
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("(link removed)", text)
    text = _WWW.sub("(link removed)", text)
    return text.replace("@", "@​")


_defang = defang


# --------------------------------------------------------------------------- reading the project


async def _people(ctx: ServiceContext, project: Project) -> list[Person]:
    """People who may own work here (editors and admins), with their open task counts."""
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
    ids = {u for u, r in explicit if r in (ProjectRole.EDITOR, ProjectRole.ADMIN)} | {
        u for u, r in via_ws if r in (WorkspaceRole.ADMIN, WorkspaceRole.MEMBER)
    }
    if not ids:
        return []
    users = (
        await ctx.session.execute(
            select(User.id, User.name).where(
                User.id.in_(ids), User.is_active.is_(True), User.kind != ASSISTANT_KIND
            )
        )
    ).all()
    open_counts = await ctx.session.execute(
        select(Task.assignee_id, func.count())
        .join(ProjectStatus, ProjectStatus.id == Task.status_id)
        .where(
            Task.project_id == project.id,
            Task.deleted_at.is_(None),
            Task.assignee_id.in_([u.id for u in users]),
            ProjectStatus.category.in_(OPEN),
        )
        .group_by(Task.assignee_id)
    )
    counts = dict(open_counts.all())
    return sorted((Person(u.id, u.name, counts.get(u.id, 0)) for u in users), key=lambda p: (p.open, p.name))


async def _open_tasks(ctx: ServiceContext, project: Project) -> list[OpenTask]:
    rows = (
        await ctx.session.execute(
            select(Task, ProjectStatus, User.name)
            .join(ProjectStatus, ProjectStatus.id == Task.status_id)
            .outerjoin(User, User.id == Task.assignee_id)
            .where(Task.project_id == project.id, Task.deleted_at.is_(None), ProjectStatus.category.in_(OPEN))
        )
    ).all()
    return [
        OpenTask(
            id=t.id,
            key=f"{project.key}-{t.number}",
            title=t.title,
            category=s.category,
            status=s.name,
            assignee_id=t.assignee_id,
            assignee=name,
            due_date=t.due_date,
            start_date=t.start_date,
            updated_at=t.updated_at,
        )
        for t, s, name in rows
    ]


# --------------------------------------------------------------------------- rules


def rule_drafts(
    tasks: list[OpenTask], people: list[Person], *, today: date, now: datetime, stale_days: int
) -> list[Draft]:
    """Plain suggestions that need no AI: nudge overdue and stale work, date long-overdue work that
    has not started, and give unassigned work due soon to whoever has the fewest open tasks."""
    drafts: list[Draft] = []
    soon = today + timedelta(days=7)
    for t in sorted(tasks, key=lambda t: (t.due_date or date.max, t.key)):
        late = (today - t.due_date).days if t.due_date and t.due_date < today else 0
        quiet = (now - t.updated_at).days
        if t.assignee_id and t.assignee and late:
            drafts.append(
                Draft(
                    "comment",
                    "rules",
                    f"{late} day{'s' if late != 1 else ''} overdue",
                    {
                        "comment": f"{_mention(t.assignee_id, t.assignee)} this was due "
                        f"{t.due_date:%b %-d}. What's a realistic new date, or is something blocking it?"
                    },
                    t.id,
                    f"comment:{t.id}",
                )
            )
        elif (
            t.assignee_id and t.assignee and t.category == StatusCategory.IN_PROGRESS and quiet >= stale_days
        ):
            drafts.append(
                Draft(
                    "comment",
                    "rules",
                    f"No update for {quiet} days",
                    {
                        "comment": f"{_mention(t.assignee_id, t.assignee)} this hasn't had an update in "
                        f"{quiet} days. Is it still on track, and is anything blocking it?"
                    },
                    t.id,
                    f"comment:{t.id}",
                )
            )
        if late >= 7 and t.category in NOT_STARTED:
            new = today + timedelta(days=7)
            if t.start_date is None or t.start_date <= new:
                drafts.append(
                    Draft(
                        "due_date",
                        "rules",
                        f"{late} days overdue and not started; a realistic date keeps the plan honest",
                        {"to": new.isoformat(), "from": t.due_date.isoformat() if t.due_date else None},
                        t.id,
                        f"due_date:{t.id}",
                    )
                )
        if t.assignee_id is None and t.due_date and t.due_date <= soon and people:
            who = people[0]
            when = "overdue" if late else f"due {t.due_date:%b %-d}"
            drafts.append(
                Draft(
                    "assign",
                    "rules",
                    f"Unassigned and {when}; {who.name} has the fewest open tasks ({who.open})",
                    {"to": str(who.id), "from": None},
                    t.id,
                    f"assign:{t.id}",
                )
            )
    return drafts


def note_lines(text: str) -> list[str]:
    """Action items in notes without AI: '- [ ] …', 'TODO: …', 'Action: …', 'AI: …'."""
    found = []
    for line in text.splitlines():
        m = NOTE_LINE.match(line)
        if m and m.group(1).strip():
            found.append(m.group(1).strip()[:500])
    return found[:MAX_NOTE_TASKS]


# --------------------------------------------------------------------------- AI


class _AiSuggestion(BaseModel):
    kind: Literal["comment", "due_date", "assign"]
    task_key: str = Field(description="A task key from the data.")
    comment: str | None = Field(description="kind=comment: a short, friendly follow-up (no @mentions).")
    new_due_date: date | None = Field(description="kind=due_date: a realistic new due date.")
    assignee: str | None = Field(description="kind=assign: a person's name from the people list.")
    reason: str = Field(description="One short sentence: why, citing the data.")


class SuggestOutput(BaseModel):
    suggestions: list[_AiSuggestion] = Field(description="At most 8, most useful first.")


class _NoteTask(BaseModel):
    title: str = Field(description="Short, imperative task title.")
    description: str = Field(description="What to do and how to tell it is done (Markdown).")
    priority: Literal["none", "low", "medium", "high", "urgent"]
    due_date: date | None = Field(description="Only when the notes give a date.")
    assignee: str | None = Field(description="Only when the notes name an owner from the people list.")


class NotesOutput(BaseModel):
    tasks: list[_NoteTask] = Field(description=f"At most {MAX_NOTE_TASKS} action items from the notes.")


def _ai_payload(project: Project, tasks: list[OpenTask], people: list[Person], today: date) -> dict[str, Any]:
    def rank(t: OpenTask) -> tuple[int, date]:
        late = t.due_date is not None and t.due_date < today
        return (0 if late else 1 if t.assignee_id is None else 2, t.due_date or date.max)

    return {
        "project": {"key": project.key, "name": project.name},
        "today": today.isoformat(),
        "people": [{"name": p.name, "open_tasks": p.open} for p in people],
        "open_tasks": [
            {
                "key": t.key,
                "title": t.title,
                "status": t.status,
                "owner": t.assignee,
                "due": t.due_date.isoformat() if t.due_date else None,
                "days_since_update": (datetime.now(UTC) - t.updated_at).days,
            }
            for t in sorted(tasks, key=rank)[:60]
        ],
    }


def ai_drafts(out: SuggestOutput, tasks: list[OpenTask], people: list[Person], today: date) -> list[Draft]:
    """Keep only what the data supports: known tasks, real people, sensible dates."""
    by_key = {t.key: t for t in tasks}
    by_name = _by_name(people)
    drafts: list[Draft] = []
    for s in out.suggestions[:8]:
        t = by_key.get(s.task_key.strip().upper())
        reason = s.reason.strip()[:300] or "Suggested by the assistant"
        if t is None:
            continue
        if s.kind == "comment" and s.comment and s.comment.strip():
            text = _defang(s.comment.strip()[:1000])
            if t.assignee_id and t.assignee:
                text = f"{_mention(t.assignee_id, t.assignee)} {text}"
            drafts.append(Draft("comment", "ai", reason, {"comment": text}, t.id, f"comment:{t.id}"))
        elif s.kind == "due_date" and s.new_due_date:
            if not (today < s.new_due_date <= today + timedelta(days=365)) or s.new_due_date == t.due_date:
                continue
            if t.start_date and t.start_date > s.new_due_date:
                continue
            data = {"to": s.new_due_date.isoformat(), "from": t.due_date.isoformat() if t.due_date else None}
            drafts.append(Draft("due_date", "ai", reason, data, t.id, f"due_date:{t.id}"))
        elif s.kind == "assign" and s.assignee:
            p = by_name.get(s.assignee.strip().lower())
            if p is None or p.id == t.assignee_id:
                continue
            data = {"to": str(p.id), "from": str(t.assignee_id) if t.assignee_id else None}
            drafts.append(Draft("assign", "ai", reason, data, t.id, f"assign:{t.id}"))
    return drafts


def merge(rules: list[Draft], ai: list[Draft]) -> list[Draft]:
    """The model's suggestion wins over the rule's for the same task and kind."""
    seen = {d.dedupe_key for d in ai}
    return ai + [d for d in rules if d.dedupe_key not in seen]


# --------------------------------------------------------------------------- storing


async def _store(
    ctx: ServiceContext, project_id: uuid.UUID, drafts: list[Draft]
) -> list[AssistantSuggestion]:
    now = datetime.now(UTC)
    await ctx.session.execute(
        update(AssistantSuggestion)
        .where(
            AssistantSuggestion.project_id == project_id,
            AssistantSuggestion.status == "open",
            AssistantSuggestion.source != "notes",
            AssistantSuggestion.created_at < now - timedelta(days=EXPIRE_DAYS),
        )
        .values(status="expired", decided_at=now)
    )
    open_keys = set(
        (
            await ctx.session.scalars(
                select(AssistantSuggestion.dedupe_key).where(
                    AssistantSuggestion.project_id == project_id, AssistantSuggestion.status == "open"
                )
            )
        ).all()
    )
    quiet = set(
        (
            await ctx.session.scalars(
                select(AssistantSuggestion.dedupe_key).where(
                    AssistantSuggestion.project_id == project_id,
                    # Expired too: an ignored suggestion is not simply proposed again the same day.
                    AssistantSuggestion.status.in_(("approved", "dismissed", "undone", "expired")),
                    AssistantSuggestion.decided_at > now - timedelta(days=QUIET_DAYS),
                )
            )
        ).all()
    )
    room = MAX_OPEN - len(open_keys)
    notes_room = MAX_OPEN_NOTES - (
        await ctx.session.scalar(
            select(func.count()).where(
                AssistantSuggestion.project_id == project_id,
                AssistantSuggestion.status == "open",
                AssistantSuggestion.source == "notes",
            )
        )
        or 0
    )
    added: list[AssistantSuggestion] = []
    for d in drafts:
        if d.source == "notes":
            if notes_room <= 0:
                continue
            notes_room -= 1
        elif len(added) >= min(room, MAX_NEW_PER_RUN):
            break
        if d.dedupe_key and (d.dedupe_key in open_keys or d.dedupe_key in quiet):
            continue
        row = AssistantSuggestion(
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            task_id=d.task_id,
            kind=d.kind,
            source=d.source,
            reason=d.reason[:500],
            data=d.data,
            dedupe_key=d.dedupe_key,
        )
        ctx.session.add(row)
        if d.dedupe_key:
            open_keys.add(d.dedupe_key)
        added.append(row)
    await ctx.session.flush()
    return added


async def open_count(ctx: ServiceContext, project_id: uuid.UUID) -> int:
    return (
        await ctx.session.scalar(
            select(func.count()).where(
                AssistantSuggestion.project_id == project_id, AssistantSuggestion.status == "open"
            )
        )
    ) or 0


async def refresh(tenant_id: uuid.UUID, project_id: uuid.UUID, *, tz: str, stale_days: int) -> int:
    """Propose what today's data calls for (worker and "write a digest now"). Returns the open count."""
    from glasshaus.ai import service as ai
    from glasshaus.assistant import service as assistant

    account = await assistant._account_for(tenant_id, project_id)
    actor = assistant._account_actor(tenant_id, account)
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo(tz)).date()
    async with unit_of_work(actor) as ctx:
        project = await require_project(ctx, project_id, Permission.PROJECT_READ)
        tasks = await _open_tasks(ctx, project)
        people = await _people(ctx, project)
        use_ai = await assistant.ai_allowed(ctx)
        payload = _ai_payload(project, tasks, people, today) if use_ai and tasks else None
        key = project.key
    drafts = rule_drafts(tasks, people, today=today, now=now, stale_days=stale_days)
    if payload is not None:
        try:
            out, _ = await ai._run(
                actor,
                "assistant",
                key,
                system=(
                    "You are the project assistant, a careful junior project manager. Propose a few "
                    "helpful actions for a person to approve: a friendly follow-up comment on overdue or "
                    "stale work, a realistic new due date for work that is clearly slipping, or an owner "
                    "for unassigned work (prefer people with fewer open tasks). Only propose what the "
                    "data supports; fewer, better suggestions are best. " + ai.GUARD
                ),
                prompt=f"Suggest actions for today.\n\n{ai._data(payload)}",
                output=SuggestOutput,
                max_tokens=3000,
            )
            drafts = merge(drafts, ai_drafts(out, tasks, people, today))
        except ServiceError as exc:
            log.info("assistant.suggest_ai_skipped", project=key, reason=str(exc))
        except Exception:  # the rules still stand when the model fails
            log.exception("assistant.suggest_ai_failed", project=key)
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        await _lock(ctx, project_id)
        await _store(ctx, project_id, drafts)
        applied = await _auto_apply(ctx, project_id, account, today=today, tz=tz)
        waiting = await open_count(ctx, project_id)
    for key_, suggestion_id in applied:
        await audit.record(
            actor,
            "assistant.action_automatic",
            outcome="ok",
            target=key_,
            detail={"suggestion": str(suggestion_id), "kind": "comment"},
        )
    return waiting


AUTO_NOTE = (
    "Posted automatically by the project assistant. Project editors and admins can undo it on the "
    "project's Digests page."
)
UNDO_DAYS = 7


async def trusted_kinds(ctx: ServiceContext, project_id: uuid.UUID) -> set[str]:
    """What the project trusts the assistant with, within the organization's ceiling."""
    from glasshaus.assistant.models import ProjectAssistant
    from glasshaus.governance.models import OrgSettings

    a = await ctx.session.scalar(select(ProjectAssistant).where(ProjectAssistant.project_id == project_id))
    org = await ctx.session.get(OrgSettings, ctx.tenant_id)
    if a is None or not a.enabled or org is None:
        return set()
    return set(a.trusted) & set(org.assistant_trusted)


async def _lock(ctx: ServiceContext, project_id: uuid.UUID) -> None:
    """One refresh at a time per project (the worker and "write a digest now" can overlap): the
    duplicate check and the daily cap count are then exact."""
    from glasshaus.assistant.models import ProjectAssistant

    await ctx.session.execute(
        select(ProjectAssistant.project_id).where(ProjectAssistant.project_id == project_id).with_for_update()
    )


async def _auto_apply(
    ctx: ServiceContext, project_id: uuid.UUID, account_id: uuid.UUID, *, today: date, tz: str
) -> list[tuple[str, uuid.UUID]]:
    """Post trusted follow-ups straight away, up to the project's daily cap. Returns (task key, id)."""
    from glasshaus.assistant.models import ProjectAssistant
    from glasshaus.collab import service as collab
    from glasshaus.collab.schemas import CommentCreate

    if "comment" not in await trusted_kinds(ctx, project_id):
        return []
    a = await ctx.session.scalar(select(ProjectAssistant).where(ProjectAssistant.project_id == project_id))
    assert a is not None
    project = await ctx.session.get(Project, project_id)
    assert project is not None
    midnight = datetime.combine(today, datetime.min.time(), ZoneInfo(tz))
    done_today = [
        r
        for r in (
            await ctx.session.scalars(
                select(AssistantSuggestion).where(
                    AssistantSuggestion.project_id == project_id,
                    AssistantSuggestion.decided_at >= midnight,
                    AssistantSuggestion.status.in_(("approved", "undone")),
                )
            )
        ).all()
        if r.data.get("auto")
    ]
    room = a.auto_daily_cap - len(done_today)
    if room <= 0:
        return []
    rows = (
        await ctx.session.scalars(
            select(AssistantSuggestion)
            .where(
                AssistantSuggestion.project_id == project_id,
                AssistantSuggestion.status == "open",
                AssistantSuggestion.kind == "comment",
                # Only today's: an older follow-up may no longer fit (the date moved, work resumed),
                # so it waits for a person instead of being posted when trust is turned on.
                AssistantSuggestion.created_at >= midnight,
            )
            .order_by(AssistantSuggestion.created_at)
            .limit(room)
            .with_for_update(skip_locked=True)
        )
    ).all()
    acting = _as_assistant(ctx, account_id, project_id)
    applied: list[tuple[str, uuid.UUID]] = []
    now = datetime.now(UTC)
    for row in rows:
        task = await ctx.session.get(Task, row.task_id) if row.task_id else None
        status = await ctx.session.get(ProjectStatus, task.status_id) if task else None
        if task is None or _stale(row, task, status):
            continue  # left for a person to look at
        body = row.data["comment"]
        comment = await collab.create_comment(acting, task.id, CommentCreate(body=f"{body}\n\n_{AUTO_NOTE}_"))
        key = f"{project.key}-{task.number}"
        row.status, row.decided_at = "approved", now
        row.result = f"Posted automatically on {key}"
        row.data = {**row.data, "comment_id": str(comment.id), "auto": True}
        applied.append((key, row.id))
    ctx.pending_events.extend(acting.pending_events)
    await ctx.session.flush()
    return applied


async def from_notes(actor: Actor, project_id: uuid.UUID, text: str) -> list[SuggestionRead]:
    """Propose tasks from meeting notes or an email (people who can create tasks)."""
    from glasshaus.ai import service as ai
    from glasshaus.assistant import service as assistant

    async with unit_of_work(actor) as ctx:
        project = await require_project(ctx, project_id, Permission.TASK_CREATE)
        a = await assistant._settings(ctx, project_id)
        if a is None or not a.enabled:
            raise InvalidInput("turn the assistant on for this project first")
        use_ai = await assistant.ai_allowed(ctx)
        people = await _people(ctx, project)
        key, name = project.key, project.name
    await assistant._limit_run_now(actor)
    drafts: list[Draft] = []
    if use_ai:
        account = await assistant._account_for(actor.tenant_id, project_id)
        out, _ = await ai._run(
            assistant._account_actor(actor.tenant_id, account),
            "assistant",
            key,
            system=(
                "You turn meeting notes or an email into clear tasks for a project management tool. "
                "Only include real action items; leave out discussion and decisions that need no work. "
                + ai.GUARD
            ),
            prompt=(
                "Propose tasks from these notes.\n\n"
                + ai._data(
                    {
                        "project": {"key": key, "name": name},
                        "people": [p.name for p in people],
                        "notes": text,
                    }
                )
            ),
            output=NotesOutput,
            max_tokens=5000,
        )
        by_name = _by_name(people)
        for t in out.tasks[:MAX_NOTE_TASKS]:
            title = t.title.strip()[:500]
            if not title:
                continue
            owner = by_name.get((t.assignee or "").strip().lower())
            new = NewTask(
                title=title,
                description=t.description.strip()[:20_000],
                priority=t.priority,
                due_date=t.due_date if t.due_date and t.due_date >= date.today() else None,
                assignee_id=owner.id if owner else None,
            )
            drafts.append(Draft("task", "notes", "From the notes", {"task": new.model_dump(mode="json")}))
    else:
        for line in note_lines(text):
            new = NewTask(title=line)
            drafts.append(
                Draft("task", "notes", "Action item in the notes", {"task": new.model_dump(mode="json")})
            )
    if not drafts:
        raise InvalidInput(
            "no action items found; with AI off, start lines with '- [ ]', 'TODO:' or 'Action:'"
        )
    async with unit_of_work(Actor.system(actor.tenant_id)) as ctx:
        await _lock(ctx, project_id)
        rows = await _store(ctx, project_id, drafts)
        if not rows:
            raise InvalidInput(
                f"{MAX_OPEN_NOTES} tasks from notes are already waiting; approve or dismiss some first"
            )
        return await _reads(ctx, rows, key)


# --------------------------------------------------------------------------- reading


async def _reads(ctx: ServiceContext, rows: list[AssistantSuggestion], key: str) -> list[SuggestionRead]:
    task_ids = {r.task_id for r in rows if r.task_id}
    tasks = {
        t.id: t
        for t in (
            (await ctx.session.scalars(select(Task).where(Task.id.in_(task_ids)))).all() if task_ids else []
        )
    }
    people = {r.decided_by for r in rows if r.decided_by}
    for r in rows:
        if r.kind == "assign":
            people.add(uuid.UUID(r.data["to"]))
        if r.kind == "task" and r.data["task"].get("assignee_id"):
            people.add(uuid.UUID(r.data["task"]["assignee_id"]))
    people |= {t.assignee_id for t in tasks.values() if t.assignee_id}
    names: dict[uuid.UUID, str] = {}
    if people:
        found = await ctx.session.execute(select(User.id, User.name).where(User.id.in_(people)))
        names = dict(found.all())
    out = []
    undo_after = datetime.now(UTC) - timedelta(days=UNDO_DAYS)
    for r in rows:
        t = tasks.get(r.task_id) if r.task_id else None
        out.append(
            SuggestionRead(
                id=r.id,
                project_id=r.project_id,
                kind=r.kind,
                source=r.source,
                status=r.status,
                reason=r.reason,
                task=SuggestionTask(
                    id=t.id,
                    key=f"{key}-{t.number}",
                    title=t.title,
                    due_date=t.due_date,
                    assignee=names.get(t.assignee_id) if t.assignee_id else None,
                )
                if t
                else None,
                comment=r.data.get("comment"),
                due_date=date.fromisoformat(r.data["to"]) if r.kind == "due_date" else None,
                assignee_id=uuid.UUID(r.data["to"]) if r.kind == "assign" else None,
                assignee=names.get(uuid.UUID(r.data["to"])) if r.kind == "assign" else None,
                new_task=NewTask.model_validate(r.data["task"]) if r.kind == "task" else None,
                created_at=r.created_at,
                decided_at=r.decided_at,
                decided_by=names.get(r.decided_by) if r.decided_by else None,
                automatic=bool(r.data.get("auto")),
                can_undo=r.status == "approved"
                and r.kind == "comment"
                and "comment_id" in r.data
                and r.decided_at is not None
                and r.decided_at > undo_after,
                result=r.result,
            )
        )
    return out


async def list_suggestions(
    ctx: ServiceContext, project_id: uuid.UUID, *, decided: bool = False, limit: int = 50
) -> list[SuggestionRead]:
    project = await require_project(ctx, project_id, Permission.PROJECT_READ)
    stmt = select(AssistantSuggestion).where(AssistantSuggestion.project_id == project_id)
    if decided:
        stmt = stmt.where(AssistantSuggestion.status != "open").order_by(
            AssistantSuggestion.decided_at.desc().nulls_last()
        )
    else:
        stmt = stmt.where(AssistantSuggestion.status == "open").order_by(AssistantSuggestion.created_at)
    rows = list((await ctx.session.scalars(stmt.limit(min(max(limit, 1), 100)))).all())
    return await _reads(ctx, rows, project.key)


async def can_approve(ctx: ServiceContext, project: Project) -> bool:
    role = await project_role(ctx, project)
    return ctx.actor.user_id is not None and role in (ProjectRole.EDITOR, ProjectRole.ADMIN)


# --------------------------------------------------------------------------- deciding


async def _open_suggestion(
    ctx: ServiceContext, project_id: uuid.UUID, suggestion_id: uuid.UUID
) -> tuple[Project, AssistantSuggestion]:
    project = await require_project(ctx, project_id, Permission.TASK_UPDATE)
    if not await can_approve(ctx, project):
        raise NotFound("suggestion not found")
    row = await ctx.session.get(AssistantSuggestion, suggestion_id, with_for_update=True)
    if row is None or row.project_id != project_id:
        raise NotFound("suggestion not found")
    if row.status != "open":
        raise Conflict(f"this suggestion was already {row.status}")
    return project, row


def _as_assistant(ctx: ServiceContext, account_id: uuid.UUID, project_id: uuid.UUID) -> ServiceContext:
    """The assistant acting in this transaction with editor rights on this one project, because a
    person allowed to make the change approved it. It never holds those rights outside this call."""
    acting = ServiceContext(
        session=ctx.session,
        actor=Actor(tenant_id=ctx.tenant_id, user_id=account_id, org_role=OrgRole.GUEST, method="system"),
    )
    acting.cache[("project_role", project_id)] = ProjectRole.EDITOR
    return acting


def _stale(row: AssistantSuggestion, task: Task | None, status: ProjectStatus | None) -> str | None:
    if task is None or task.deleted_at is not None:
        return "the task was deleted"
    if status is not None and status.category not in OPEN:
        return "the task is already closed"
    if row.kind == "due_date" and (task.due_date.isoformat() if task.due_date else None) != row.data.get(
        "from"
    ):
        return "the task's due date changed since this was suggested"
    if row.kind == "assign" and (str(task.assignee_id) if task.assignee_id else None) != row.data.get("from"):
        return "the task's owner changed since this was suggested"
    return None


async def approve(
    actor: Actor, project_id: uuid.UUID, suggestion_id: uuid.UUID, data: SuggestionDecision
) -> SuggestionRead:
    """Apply a suggestion (with any edits) as the assistant, naming the approver."""
    from glasshaus.assistant import service as assistant
    from glasshaus.collab import service as collab
    from glasshaus.collab.schemas import CommentCreate
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskCreate, TaskUpdate

    stale_reason: str | None = None
    async with unit_of_work(actor) as ctx:
        project, row = await _open_suggestion(ctx, project_id, suggestion_id)
        approver = await ctx.session.get(User, actor.user_id)
        assert approver is not None
        signed = f"Suggested by the project assistant, approved by {approver.name}."
        task = await ctx.session.get(Task, row.task_id) if row.task_id else None
        status = await ctx.session.get(ProjectStatus, task.status_id) if task else None
        if row.kind != "task":
            stale_reason = _stale(row, task, status)
        if stale_reason is None:
            account = await assistant.ensure_account(ctx)
            acting = _as_assistant(ctx, account.id, project.id)
            if row.kind == "comment":
                assert task is not None
                body = data.comment or row.data["comment"]
                comment = await collab.create_comment(
                    acting, task.id, CommentCreate(body=f"{body}\n\n_{signed}_")
                )
                row.result = f"Comment posted on {project.key}-{task.number}"
                row.data = {**row.data, "comment": body, "comment_id": str(comment.id)}
            elif row.kind == "due_date":
                assert task is not None
                due = data.due_date or date.fromisoformat(row.data["to"])
                await tasks.update_task(acting, task.id, TaskUpdate(due_date=due))
                row.result = f"{project.key}-{task.number} now due {due:%b %-d, %Y}"
                row.data = {**row.data, "to": due.isoformat()}
            elif row.kind == "assign":
                assert task is not None
                owner = data.assignee_id or uuid.UUID(row.data["to"])
                await tasks.update_task(acting, task.id, TaskUpdate(assignee_id=owner))
                row.result = f"{project.key}-{task.number} assigned"
                row.data = {**row.data, "to": str(owner)}
            else:
                new = data.new_task or NewTask.model_validate(row.data["task"])
                created = await tasks.create_task(
                    acting,
                    TaskCreate(
                        project_id=project.id,
                        title=new.title,
                        description=(new.description + "\n\n" if new.description else "") + f"_{signed}_",
                        priority=new.priority,
                        due_date=new.due_date,
                        assignee_id=new.assignee_id,
                    ),
                )
                row.task_id = created.id
                row.result = f"Created {created.key}"
                row.data = {**row.data, "task": new.model_dump(mode="json")}
            ctx.pending_events.extend(acting.pending_events)
            row.status = "approved"
        else:
            row.status, row.result = "stale", stale_reason
        row.decided_by, row.decided_at = actor.user_id, datetime.now(UTC)
        await ctx.session.flush()
        result = (await _reads(ctx, [row], project.key))[0]
    await audit.record(
        actor,
        "assistant.suggestion_approved" if stale_reason is None else "assistant.suggestion_stale",
        outcome="ok" if stale_reason is None else "denied",
        target=result.task.key if result.task else project.key,
        detail={"suggestion": str(suggestion_id), "kind": result.kind, "source": result.source},
    )
    if stale_reason is not None:
        raise Conflict(f"Not applied: {stale_reason}. It has been set aside.")
    return result


async def dismiss(ctx: ServiceContext, project_id: uuid.UUID, suggestion_id: uuid.UUID) -> SuggestionRead:
    project, row = await _open_suggestion(ctx, project_id, suggestion_id)
    row.status, row.decided_by, row.decided_at = "dismissed", ctx.actor.user_id, datetime.now(UTC)
    await ctx.session.flush()
    return (await _reads(ctx, [row], project.key))[0]


async def undo(actor: Actor, project_id: uuid.UUID, suggestion_id: uuid.UUID) -> SuggestionRead:
    """Take back a follow-up the assistant posted (within 7 days): the comment is deleted."""
    from glasshaus.assistant import service as assistant
    from glasshaus.collab import service as collab
    from glasshaus.collab.models import Comment

    async with unit_of_work(actor) as ctx:
        project = await require_project(ctx, project_id, Permission.TASK_UPDATE)
        if not await can_approve(ctx, project):
            raise NotFound("suggestion not found")
        row = await ctx.session.get(AssistantSuggestion, suggestion_id, with_for_update=True)
        if row is None or row.project_id != project_id:
            raise NotFound("suggestion not found")
        if row.status != "approved" or row.kind != "comment" or "comment_id" not in row.data:
            raise Conflict("only a follow-up comment the assistant posted can be undone")
        if row.decided_at is None or row.decided_at < datetime.now(UTC) - timedelta(days=UNDO_DAYS):
            raise Conflict(f"follow-ups can be undone for {UNDO_DAYS} days")
        person = await ctx.session.get(User, actor.user_id)
        assert person is not None
        comment = await ctx.session.get(Comment, uuid.UUID(row.data["comment_id"]))
        if comment is not None and comment.deleted_at is None:
            account = await assistant.ensure_account(ctx)
            acting = _as_assistant(ctx, account.id, project.id)
            await collab.delete_comment(acting, comment.id)
            ctx.pending_events.extend(acting.pending_events)
        row.status, row.result = "undone", f"Undone by {person.name}"
        row.data = {**row.data, "undone_by": str(actor.user_id)}
        await ctx.session.flush()
        result = (await _reads(ctx, [row], project.key))[0]
    await audit.record(
        actor,
        "assistant.action_undone",
        outcome="ok",
        target=result.task.key if result.task else project.key,
        detail={"suggestion": str(suggestion_id), "automatic": result.automatic},
    )
    return result
