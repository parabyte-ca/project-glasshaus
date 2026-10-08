"""Rule evaluation and action execution. Pure decisions + service-layer effects; no HTTP here.

Safety: task, comment and field text is data. Placeholders are substituted from a fixed whitelist
and never evaluated; nothing in task content can choose which actions run.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from glasshaus.automation.schemas import Action, ActionType, Condition, Operator
from glasshaus.config import get_settings
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput
from glasshaus.projects.models import Project, ProjectStatus
from glasshaus.tasks.schemas import TaskRead

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_.]+)\s*\}\}")


@dataclass
class WebhookCall:
    url: str
    payload: dict[str, Any]


@dataclass
class Outcome:
    actions: list[dict[str, Any]] = field(default_factory=list)
    webhooks: list[WebhookCall] = field(default_factory=list)
    notified: list[str] = field(default_factory=list)


def task_value(task: TaskRead, name: str, today: date) -> Any:
    if name == "status_category":
        return task.status.category.value
    if name == "status_id":
        return str(task.status.id)
    if name == "priority":
        return task.priority.value
    if name == "assignee_id":
        return str(task.assignee_id) if task.assignee_id else None
    if name == "tags":
        return task.tags
    if name == "title":
        return task.title
    if name == "due_in_days":
        return (task.due_date - today).days if task.due_date else None
    if name == "is_subtask":
        return task.parent_id is not None
    if name.startswith("cf:"):
        return task.custom_fields.get(name[3:])
    raise InvalidInput(f"unknown condition field {name}")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def condition_holds(cond: Condition, task: TaskRead, today: date) -> bool:
    actual = task_value(task, cond.field, today)
    expected = cond.value
    match cond.op:
        case Operator.IS_EMPTY:
            return bool(actual in (None, "", []))
        case Operator.NOT_EMPTY:
            return bool(actual not in (None, "", []))
        case Operator.EQ:
            return bool(_norm(actual) == _norm(expected))
        case Operator.NEQ:
            return bool(_norm(actual) != _norm(expected))
        case Operator.IN:
            return _norm(actual) in [_norm(v) for v in _as_list(expected)]
        case Operator.NOT_IN:
            return _norm(actual) not in [_norm(v) for v in _as_list(expected)]
        case Operator.CONTAINS | Operator.NOT_CONTAINS:
            if isinstance(actual, list):
                found = any(_norm(v) in [_norm(a) for a in actual] for v in _as_list(expected))
            else:
                found = str(expected).lower() in str(actual or "").lower()
            return found if cond.op == Operator.CONTAINS else not found
        case Operator.LT | Operator.GT:
            try:
                a, e = float(actual), float(expected)
            except (TypeError, ValueError):
                return False
            return a < e if cond.op == Operator.LT else a > e
    return False  # pragma: no cover


def _norm(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def evaluate(conditions: list[Condition], task: TaskRead, today: date) -> list[tuple[Condition, bool]]:
    return [(c, condition_holds(c, task, today)) for c in conditions]


def render(text: str, task: TaskRead | None, project: Project, rule_name: str) -> str:
    base = get_settings().public_url.rstrip("/")
    values: dict[str, str] = {
        "project.name": project.name,
        "project.key": project.key,
        "rule.name": rule_name,
    }
    if task is not None:
        values |= {
            "task.key": task.key,
            "task.title": task.title,
            "task.status": task.status.name,
            "task.priority": task.priority.value,
            "task.due_date": task.due_date.isoformat() if task.due_date else "",
            "task.url": f"{base}/projects/{project.key}?task={task.key}",
        }
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def describe(action: Action) -> str:
    detail = {
        ActionType.SET_STATUS: f"status → {action.status_category or action.status_id}",
        ActionType.SET_PRIORITY: f"priority → {action.priority}",
        ActionType.ASSIGN: f"assign → {action.user}",
        ActionType.SET_DUE_DATE: f"due date → today {action.days_from_now:+d}d"
        if action.days_from_now is not None
        else "",
        ActionType.ADD_TAGS: f"add tags {action.tags}",
        ActionType.REMOVE_TAGS: f"remove tags {action.tags}",
        ActionType.SET_CUSTOM_FIELD: f"field {action.field_id} → {action.value!r}",
        ActionType.CREATE_SUBTASK: f"create subtask '{action.title}'",
        ActionType.POST_COMMENT: "post a comment",
        ActionType.NOTIFY: f"notify {action.users}",
        ActionType.WEBHOOK: f"POST {action.url}",
    }.get(action.type, "")
    return f"{action.type.value}: {detail}" if detail else action.type.value


async def _status_for(ctx: ServiceContext, project_id: uuid.UUID, action: Action) -> uuid.UUID:
    from sqlalchemy import select

    stmt = select(ProjectStatus.id).where(ProjectStatus.project_id == project_id)
    if action.status_id:
        stmt = stmt.where(ProjectStatus.id == action.status_id)
    else:
        stmt = stmt.where(ProjectStatus.category == action.status_category).order_by(ProjectStatus.position)
    status_id = await ctx.session.scalar(stmt.limit(1))
    if status_id is None:
        raise InvalidInput("status not found in this project")
    return status_id


def _resolve_user(ref: str, task: TaskRead | None, actor_id: str | None) -> uuid.UUID | None:
    if ref == "assignee":
        return task.assignee_id if task else None
    if ref == "reporter":
        return task.reporter_id if task else None
    if ref == "actor":
        return uuid.UUID(actor_id) if actor_id else None
    try:
        return uuid.UUID(ref)
    except ValueError as exc:
        raise InvalidInput(f"unknown user reference {ref!r}") from exc


async def execute(
    ctx: ServiceContext,
    project: Project,
    rule_name: str,
    actions: list[Action],
    task: TaskRead | None,
    *,
    event: dict[str, Any] | None,
) -> Outcome:
    """Run database actions through the service layer (caller owns the transaction).
    Webhooks are returned, not sent: they go out after commit."""
    from glasshaus.collab import service as collab
    from glasshaus.collab.schemas import CommentCreate
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskCreate, TaskUpdate

    out = Outcome()
    actor_id = (event or {}).get("actor", {}).get("user_id")
    today = datetime.now(UTC).date()
    for action in actions:
        needs_task = action.type not in (ActionType.WEBHOOK, ActionType.NOTIFY)
        if needs_task and task is None:
            raise InvalidInput(f"{action.type.value} needs a task")
        patch: dict[str, Any] = {}
        match action.type:
            case ActionType.SET_STATUS:
                patch["status_id"] = await _status_for(ctx, project.id, action)
            case ActionType.SET_PRIORITY:
                patch["priority"] = action.priority
            case ActionType.ASSIGN:
                patch["assignee_id"] = _resolve_user(action.user or "", task, actor_id)
            case ActionType.UNASSIGN:
                patch["assignee_id"] = None
            case ActionType.SET_DUE_DATE:
                patch["due_date"] = today + timedelta(days=action.days_from_now or 0)
            case ActionType.ADD_TAGS | ActionType.REMOVE_TAGS:
                assert task is not None
                current = set(task.tags)
                change = {t.strip().lower() for t in action.tags or []}
                patch["tags"] = sorted(
                    current | change if action.type == ActionType.ADD_TAGS else current - change
                )
            case ActionType.SET_CUSTOM_FIELD:
                patch["custom_fields"] = {str(action.field_id): action.value}
            case ActionType.CREATE_SUBTASK:
                assert task is not None
                child = await tasks.create_task(
                    ctx,
                    TaskCreate(
                        project_id=project.id,
                        parent_id=task.id,
                        title=render(action.title or "", task, project, rule_name),
                        description=render(action.body or "", task, project, rule_name),
                    ),
                )
                out.actions.append({"type": action.type.value, "task_id": str(child.id), "key": child.key})
                continue
            case ActionType.POST_COMMENT:
                assert task is not None
                comment = await collab.create_comment(
                    ctx, task.id, CommentCreate(body=render(action.body or "", task, project, rule_name))
                )
                out.actions.append({"type": action.type.value, "comment_id": str(comment.id)})
                continue
            case ActionType.NOTIFY:
                ids = [
                    u for raw in action.users or [] if (u := _resolve_user(raw, task, actor_id)) is not None
                ]
                created = await _notify(
                    ctx, project, task, ids, render(action.title or "", task, project, rule_name)
                )
                out.notified.extend(created)
                out.actions.append({"type": action.type.value, "users": created})
                continue
            case ActionType.WEBHOOK:
                out.webhooks.append(
                    WebhookCall(
                        url=action.url or "",
                        payload={
                            "rule": rule_name,
                            "project": {"id": str(project.id), "key": project.key, "name": project.name},
                            "task": task.model_dump(mode="json") if task else None,
                            "event": event,
                            "sent_at": datetime.now(UTC).isoformat(),
                        },
                    )
                )
                continue
        assert task is not None
        task = await tasks.update_task(ctx, task.id, TaskUpdate.model_validate(patch))
        out.actions.append({"type": action.type.value, "changes": {k: str(v) for k, v in patch.items()}})
    return out


async def _notify(
    ctx: ServiceContext, project: Project, task: TaskRead | None, user_ids: list[uuid.UUID], title: str
) -> list[str]:
    """One notification per user per action (each gets its own event id); only users who can see the
    project are notified, so titles never leak."""
    from sqlalchemy.dialects.postgresql import insert

    from glasshaus.collab.handlers import _can_read
    from glasshaus.collab.models import Notification, NotificationKind

    created: list[str] = []
    for user_id in dict.fromkeys(user_ids):
        if not await _can_read(ctx, user_id, project.id):
            continue
        created.append(str(user_id))
        await ctx.session.execute(
            insert(Notification).values(
                id=uuid.uuid4(),
                tenant_id=ctx.tenant_id,
                user_id=user_id,
                kind=NotificationKind.AUTOMATION,
                task_id=task.id if task else None,
                project_id=project.id,
                actor_id=None,
                event_id=uuid.uuid4(),
                title=title[:300],
            )
        )
    return created
