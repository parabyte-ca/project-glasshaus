"""Import tasks from a spreadsheet (CSV or Excel, including exports from other tools such as Nimble).

The browser reads the file and sends rows already mapped to Glasshaus fields; this module checks them
and writes them in one transaction. Rows with an id from the source tool are remembered
(``ImportLink``), so importing the same file again updates those tasks instead of duplicating them.

Imported tasks don't send notifications, run automation rules or post to Slack/Teams one by one: a
single ``project.imported`` event records the import (activity, audit log, live refresh).
"""

import hashlib
import re
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from glasshaus.collab.models import Comment
from glasshaus.core import events
from glasshaus.core.authz import project_role, require_project
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import InvalidInput
from glasshaus.core.rbac import Permission
from glasshaus.fields.models import CustomField, FieldType
from glasshaus.fields.service import URL_RE, fields_for, merge_values
from glasshaus.identity.models import User, is_assistant
from glasshaus.imports.models import ImportLink
from glasshaus.imports.schemas import ImportProblem, ImportRequest, ImportResult, ImportRow, UnmatchedPerson
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Priority, Task
from glasshaus.tasks.schemas import _clean_tags
from glasshaus.tasks.service import CLOSED, POSITION_STEP

MAX_PROBLEMS = 200
MAX_TITLE = 500
MAX_COMMENT = 20_000
LINKS_HEADING = "**Links**"

PRIORITY_WORDS = {
    Priority.URGENT: ("urgent", "critical", "highest", "blocker", "p0", "1"),
    Priority.HIGH: ("high", "major", "important", "p1", "2"),
    Priority.MEDIUM: ("medium", "normal", "moderate", "p2", "3"),
    Priority.LOW: ("low", "minor", "lowest", "trivial", "p3", "p4", "4", "5"),
    Priority.NONE: ("none", "", "-"),
}
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
NUMERIC_DATE = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})$")
DURATION = re.compile(r"^(?:(\d+(?:[.,]\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?$", re.I)


class RowError(Exception):
    pass


def _norm(value: str | None) -> str:
    return (value or "").strip()


def parse_date(raw: str | None, fmt: str) -> date | None:
    """Spreadsheet dates: ISO, day/month/year in the chosen order, '12 Oct 2026', 'Oct 12, 2026', or an
    Excel serial number."""
    text = _norm(raw)
    if not text:
        return None
    try:
        if m := ISO_DATE.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := NUMERIC_DATE.match(text):
            a, b, c = (int(x) for x in m.groups())
            if len(m[1]) == 4:
                return date(a, b, c)
            year = c + 2000 if c < 100 else c
            order = fmt
            if order in ("auto", "ymd"):
                if a > 12 >= b:
                    order = "dmy"
                elif b > 12 >= a:
                    order = "mdy"
                else:
                    raise RowError(f"'{text}' could be day/month or month/day; choose a date format")
            return date(year, b, a) if order == "dmy" else date(year, a, b)
        words = re.findall(r"[A-Za-z]+|\d+", text)
        month = next((MONTHS[w[:3].lower()] for w in words if w[:3].lower() in MONTHS), None)
        numbers = [int(w) for w in words if w.isdigit()]
        if month and len(numbers) == 2:
            day, year = (numbers[0], numbers[1]) if numbers[1] > 31 else (numbers[1], numbers[0])
            return date(year, month, day)
        if text.isdigit() and 20_000 <= int(text) <= 80_000:  # Excel's day count (1900 system)
            return date(1899, 12, 30) + timedelta(days=int(text))
    except ValueError:
        pass
    raise RowError(f"'{text}' is not a date")


def parse_estimate(raw: str | None) -> int | None:
    """Minutes from '2.5', '2,5', '3h', '90m' or '1h 30m'; a bare number is hours."""
    text = _norm(raw)
    if not text:
        return None
    try:
        return round(float(text.replace(",", ".")) * 60)
    except ValueError:
        pass
    m = DURATION.match(text)
    if not m or not (m[1] or m[2]):
        raise RowError(f"'{text}' is not a duration")
    hours = float(m[1].replace(",", ".")) if m[1] else 0.0
    return round(hours * 60 + int(m[2] or 0))


def guess_priority(text: str) -> Priority | None:
    key = text.strip().lower()
    for priority, words in PRIORITY_WORDS.items():
        if key in words:
            return priority
    return None


def _split_links(description: str) -> tuple[str, list[str]]:
    """Separate a links block added by an earlier import from the text above it."""
    head, sep, tail = description.rpartition(LINKS_HEADING)
    lines = tail.strip().splitlines()
    if not sep or not lines or not all(line.startswith("- ") for line in lines):
        return description, []
    return head.rstrip(), [line[2:].strip() for line in lines]


def _with_links(description: str, links: list[str]) -> str:
    if not links:
        return description
    block = "\n".join([LINKS_HEADING, *(f"- {url}" for url in links)])
    return f"{description.rstrip()}\n\n{block}" if description.strip() else block


class _People:
    """Matches names in the file to people who can work in the project, by email (or unique name)."""

    def __init__(self, ctx: ServiceContext, project: Project, users: list[User]) -> None:
        self.ctx, self.project = ctx, project
        active = [u for u in users if u.is_active and not is_assistant(u)]
        self.by_email = {u.email.lower(): u for u in active}
        names = Counter(u.name.strip().lower() for u in active)
        self.by_name = {u.name.strip().lower(): u for u in active if names[u.name.strip().lower()] == 1}
        self.access: dict[uuid.UUID, bool] = {}
        self.unmatched: dict[str, list[Any]] = {}

    async def find(self, raw: str | None) -> tuple[bool, User | None]:
        """(given, user): ``given`` is False for an empty cell."""
        text = _norm(raw)
        if not text:
            return False, None
        user = self.by_email.get(text.lower()) if "@" in text else self.by_name.get(text.lower())
        if user is None:
            self._miss(text, "not found in Glasshaus")
            return True, None
        if user.id not in self.access:
            probe = ServiceContext(
                session=self.ctx.session,
                actor=Actor(
                    tenant_id=self.ctx.tenant_id, user_id=user.id, org_role=user.org_role, method="system"
                ),
            )
            self.access[user.id] = await project_role(probe, self.project) is not None
        if not self.access[user.id]:
            self._miss(text, "can't open this project")
            return True, None
        return True, user

    def _miss(self, text: str, reason: str) -> None:
        entry = self.unmatched.setdefault(text.lower(), [text, 0, reason])
        entry[1] += 1


async def _custom_value(people: _People, field: CustomField, raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    match field.type:
        case FieldType.NUMBER:
            try:
                number = float(text.replace(",", "."))
            except ValueError as exc:
                raise RowError(f"{field.name}: '{text}' is not a number") from exc
            return int(number) if number.is_integer() else number
        case FieldType.DATE:
            return text  # converted by the caller with the file's date format
        case FieldType.CHECKBOX:
            return text.lower() in ("1", "true", "yes", "y", "x", "✓", "checked", "oui")
        case FieldType.SELECT | FieldType.MULTI_SELECT:
            labels = {o["label"].strip().lower(): o["id"] for o in field.options}
            parts = (
                [p.strip() for p in re.split(r"[;,|]", text)]
                if field.type == FieldType.MULTI_SELECT
                else [text]
            )
            ids = []
            for part in filter(None, parts):
                if part.lower() not in labels:
                    raise RowError(f"{field.name}: '{part}' is not one of its options")
                ids.append(labels[part.lower()])
            return ids if field.type == FieldType.MULTI_SELECT else ids[0]
        case FieldType.USER:
            _, user = await people.find(text)
            return str(user.id) if user else None
        case _:
            return text


async def import_rows(ctx: ServiceContext, project_id: uuid.UUID, data: ImportRequest) -> ImportResult:
    project = await require_project(ctx, project_id, Permission.TASK_CREATE)
    await require_project(ctx, project_id, Permission.TASK_UPDATE)
    if project.archived_at is not None:
        raise InvalidInput("project is archived")
    mapped = set(data.fields)
    if "title" not in mapped:
        raise InvalidInput("map a column to the task title")

    statuses = list(
        (
            await ctx.session.scalars(
                select(ProjectStatus)
                .where(ProjectStatus.project_id == project.id)
                .order_by(ProjectStatus.position)
            )
        ).all()
    )
    by_id = {s.id: s for s in statuses}
    for status_id in data.status_map.values():
        if status_id not in by_id:
            raise InvalidInput("status_map names a status from another project")
    by_name = {s.name.strip().lower(): s for s in statuses}
    default_status = next(
        (s for cat in (StatusCategory.TODO, StatusCategory.BACKLOG) for s in statuses if s.category == cat),
        statuses[0] if statuses else None,
    )
    if default_status is None:
        raise InvalidInput("project has no statuses")
    fields = {str(f.id): f for f in await fields_for(ctx, project.id)}
    for key in mapped:
        if key.startswith("cf:") and key[3:] not in fields:
            raise InvalidInput(f"unknown custom field {key[3:]}")
    users = list((await ctx.session.scalars(select(User))).all())
    people = _People(ctx, project, users)

    problems: list[ImportProblem] = []
    warnings: list[str] = []
    unmapped_statuses: set[str] = set()
    unknown_priorities: set[str] = set()

    def problem(row: int, message: str) -> None:
        if len(problems) < MAX_PROBLEMS:
            problems.append(ImportProblem(row=row, message=message))

    task_links: dict[str, ImportLink] = {}
    comment_links: set[str] = set()
    for link in (
        await ctx.session.scalars(
            select(ImportLink).where(ImportLink.project_id == project.id, ImportLink.source == data.source)
        )
    ).all():
        if link.kind == "task":
            task_links[link.key] = link
        else:
            comment_links.add(link.key)
    linked_tasks = {
        t.id: t
        for t in (
            await ctx.session.scalars(
                select(Task).where(Task.id.in_([lnk.target_id for lnk in task_links.values()]))
            )
        ).all()
    }
    if "external_id" not in mapped:
        warnings.append("No ID column: importing this file again will add the tasks again.")

    # ---- check every row (no writes yet)
    seen_ids: set[str] = set()
    plans: list[tuple[ImportRow, Task | None, dict[str, Any]]] = []
    skipped = 0
    for row in data.rows:
        ext = _norm(row.external_id)
        known = task_links.get(ext) if ext else None
        task = linked_tasks.get(known.target_id) if known else None
        if task is not None and task.project_id != project.id:
            task = None
        try:
            if ext and ext in seen_ids:
                raise RowError(f"ID '{ext[:80]}' appears more than once in the file")
            if ext:
                seen_ids.add(ext)
            if task is not None and task.deleted_at is not None:
                raise RowError("skipped: this task was deleted in Glasshaus")
            title = " ".join(_norm(row.title).split())
            if not title:
                raise RowError("no title")
            if len(title) > MAX_TITLE:
                title = title[: MAX_TITLE - 1] + "…"
            values: dict[str, Any] = {"title": title}
            if "description" in mapped or "links" in mapped:
                body, old_urls = _split_links(task.description if task else "")
                urls = old_urls
                if "links" in mapped:
                    urls = list(dict.fromkeys(u.strip() for u in row.links if u.strip()))
                    bad = [u for u in urls if not URL_RE.match(u)]
                    if bad:
                        raise RowError(f"'{bad[0][:80]}' is not an http(s) link")
                if "description" in mapped:
                    body = row.description or ""
                values["description"] = _with_links(body, urls)
            if "status" in mapped:
                text = _norm(row.status)
                status = None
                if text:
                    chosen = data.status_map.get(text.lower())
                    status = by_id[chosen] if chosen else by_name.get(text.lower())
                    if status is None:
                        unmapped_statuses.add(text)
                values["status"] = status or default_status
            if "priority" in mapped:
                text = _norm(row.priority)
                priority = data.priority_map.get(text.lower()) or guess_priority(text)
                if priority is None:
                    unknown_priorities.add(text)
                values["priority"] = priority or Priority.NONE
            if "assignee" in mapped:
                given, user = await people.find(row.assignee)
                if user is not None or not given:  # an unmatched name leaves the current owner
                    values["assignee_id"] = user.id if user else None
            for name in ("start_date", "due_date"):
                if name in mapped:
                    values[name] = parse_date(getattr(row, name), data.date_format)
            start = values.get("start_date", task.start_date if task else None)
            due = values.get("due_date", task.due_date if task else None)
            if start and due and due < start:
                raise RowError("due date is before start date")
            if "estimate" in mapped:
                minutes = parse_estimate(row.estimate)
                if minutes is not None and not 0 <= minutes <= 1_000_000:
                    raise RowError("estimate is out of range")
                values["estimate_minutes"] = minutes
            if "tags" in mapped:
                try:
                    values["tags"] = _clean_tags(re.split(r"[;,|]", row.tags or "")) or []
                except ValueError as exc:
                    raise RowError(str(exc)) from exc
            custom: dict[str, Any] = {}
            for key in mapped:
                if key.startswith("cf:"):
                    field = fields[key[3:]]
                    value = await _custom_value(people, field, row.custom_fields.get(key[3:], ""))
                    if field.type == FieldType.DATE and value:
                        parsed = parse_date(value, data.date_format)
                        value = parsed.isoformat() if parsed else None
                    custom[key[3:]] = value
            try:
                values["custom_fields"] = await merge_values(
                    ctx, project.id, task.custom_fields if task else {}, custom, creating=task is None
                )
            except InvalidInput as exc:
                raise RowError(str(exc)) from exc
        except RowError as exc:
            problem(row.row, str(exc))
            skipped += 1
            continue
        plans.append((row, task, values))

    # ---- write (inside a savepoint, so a dry run can undo it all)
    savepoint = await ctx.session.begin_nested()
    created = updated = unchanged = comments_added = 0
    new_count = sum(1 for _, task, _ in plans if task is None)
    number = 0
    position = 0.0
    if new_count:
        last_number = await ctx.session.scalar(
            update(Project)
            .where(Project.id == project.id)
            .values(task_seq=Project.task_seq + new_count)
            .returning(Project.task_seq)
        )
        number = (last_number or new_count) - new_count
        position = float(
            await ctx.session.scalar(select(func.max(Task.position)).where(Task.project_id == project.id))
            or 0
        )
    by_ext: dict[str, Task] = {}
    rows_tasks: list[tuple[ImportRow, Task]] = []
    for row, task, values in plans:
        status = values.pop("status", None)
        ext = _norm(row.external_id)
        if task is None:
            number += 1
            position += POSITION_STEP
            task = Task(
                id=uuid.uuid4(),
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                number=number,
                position=position,
                reporter_id=ctx.actor.user_id,
                **({"priority": Priority.NONE, "tags": [], "description": ""} | values),
            )
            _set_status(task, status or default_status)
            ctx.session.add(task)
            if ext:
                new_link = task_links.get(ext)
                if new_link is None:
                    new_link = ImportLink(
                        tenant_id=ctx.tenant_id,
                        project_id=project.id,
                        source=data.source,
                        kind="task",
                        key=ext,
                        target_id=task.id,
                    )
                    ctx.session.add(new_link)
                    task_links[ext] = new_link
                new_link.target_id = task.id  # a purged task's link points at its replacement
            created += 1
        else:
            changed = False
            for key, value in values.items():
                if getattr(task, key) != value:
                    setattr(task, key, value)
                    changed = True
            if status is not None and task.status_id != status.id:
                _set_status(task, status)
                changed = True
            updated += changed
            unchanged += not changed
        if ext:
            by_ext[ext] = task
        rows_tasks.append((row, task))
    await ctx.session.flush()

    # Parents once every task exists (a child can come before its parent in the file).
    if "parent" in mapped:
        for row, task in rows_tasks:
            ref = _norm(row.parent)
            if not ref:
                continue
            parent = by_ext.get(ref)
            if parent is None and ref in task_links:
                parent = await ctx.session.get(Task, task_links[ref].target_id)
            if parent is None or parent.deleted_at is not None or parent.project_id != project.id:
                problem(row.row, f"parent '{ref[:80]}' isn't in this file or an earlier import")
            elif await _would_cycle(ctx, task, parent):
                problem(row.row, f"parent '{ref[:80]}' would make a loop")
            elif task.parent_id != parent.id:
                task.parent_id = parent.id

    # Comments: each text once per task (when the row has an ID to remember it by).
    if "comments" in mapped:
        for row, task in rows_tasks:
            ext = _norm(row.external_id)
            for text in dict.fromkeys(c.strip()[:MAX_COMMENT] for c in row.comments):
                if not text:
                    continue
                ckey = f"{ext}#{hashlib.sha256(text.encode()).hexdigest()[:32]}" if ext else None
                if ckey and ckey in comment_links:
                    continue
                ctx.session.add(
                    Comment(
                        id=uuid.uuid4(),
                        tenant_id=ctx.tenant_id,
                        task_id=task.id,
                        author_id=ctx.actor.user_id,
                        body=text,
                    )
                )
                if ckey:
                    comment_links.add(ckey)
                    ctx.session.add(
                        ImportLink(
                            tenant_id=ctx.tenant_id,
                            project_id=project.id,
                            source=data.source,
                            kind="comment",
                            key=ckey[:300],
                            target_id=task.id,
                        )
                    )
                comments_added += 1
    await ctx.session.flush()

    if unmapped_statuses:
        names = ", ".join(sorted(unmapped_statuses)[:10])
        warnings.append(f"Statuses with no match went to '{default_status.name}': {names}.")
    if unknown_priorities:
        warnings.append(
            f"Priorities with no match were left empty: {', '.join(sorted(unknown_priorities)[:10])}."
        )

    result = ImportResult(
        dry_run=data.dry_run,
        created=created,
        updated=updated,
        unchanged=unchanged,
        skipped=skipped,
        comments_added=comments_added,
        problems=problems,
        unmatched_people=[
            UnmatchedPerson(value=v, rows=n, reason=r)
            for v, n, r in sorted(people.unmatched.values(), key=lambda e: (-e[1], e[0].lower()))
        ],
        warnings=warnings,
    )
    if data.dry_run:
        await savepoint.rollback()
        return result
    await savepoint.commit()
    events.emit(
        ctx,
        "project.imported",
        "project",
        project.id,
        {
            "source": data.source,
            "file_name": data.file_name,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped": skipped,
            "comments": comments_added,
        },
    )
    return result


def _set_status(task: Task, status: ProjectStatus) -> None:
    task.status_id = status.id
    if status.category in CLOSED:
        task.completed_at = task.completed_at or datetime.now(UTC)
    else:
        task.completed_at = None


async def _would_cycle(ctx: ServiceContext, task: Task, parent: Task) -> bool:
    cursor: Task | None = parent
    for _ in range(50):
        if cursor is None:
            return False
        if cursor.id == task.id:
            return True
        cursor = await ctx.session.get(Task, cursor.parent_id) if cursor.parent_id else None
    return True
