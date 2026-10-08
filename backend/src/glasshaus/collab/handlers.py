"""Notification handlers (event consumers). Idempotent: one notification per (event, user)."""

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from glasshaus.collab.models import Notification, NotificationKind
from glasshaus.core.authz import project_role
from glasshaus.core.consumers import Event, handles
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.db import unit_of_work
from glasshaus.identity.models import User
from glasshaus.projects.models import Project


async def _can_read(ctx: ServiceContext, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    user = await ctx.session.get(User, user_id)
    project = await ctx.session.get(Project, project_id)
    if user is None or not user.is_active or project is None:
        return False
    probe = ServiceContext(
        session=ctx.session,
        actor=Actor(tenant_id=ctx.tenant_id, user_id=user.id, org_role=user.org_role, method="system"),
    )
    return await project_role(probe, project) is not None


async def _notify(event: Event, recipients: dict[uuid.UUID, tuple[NotificationKind, str]]) -> None:
    actor_id = event["actor"]["user_id"]
    if actor_id:
        recipients.pop(uuid.UUID(actor_id), None)  # never notify people about their own actions
    if not recipients or not event.get("project_id"):
        return
    tenant_id = uuid.UUID(event["tenant_id"])
    project_id = uuid.UUID(event["project_id"])
    task_id = uuid.UUID(event["aggregate_id"]) if event["aggregate_type"] == "task" else None
    created: list[str] = []
    async with unit_of_work(Actor.system(tenant_id)) as ctx:
        for user_id, (kind, title) in recipients.items():
            if not await _can_read(ctx, user_id, project_id):
                continue  # never leak titles to people who cannot see the project
            stmt = (
                insert(Notification)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind=kind,
                    task_id=task_id,
                    project_id=project_id,
                    actor_id=uuid.UUID(actor_id) if actor_id else None,
                    event_id=uuid.UUID(event["id"]),
                    title=title[:300],
                )
                .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
            )
            if (await ctx.session.execute(stmt)).rowcount:  # type: ignore[attr-defined]
                created.append(str(user_id))
    if created:
        from glasshaus.realtime import publish_user_signal

        await publish_user_signal(tenant_id, created, "notification.created")


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


@handles("comment.created", "comment.updated")
async def on_comment(event: Event) -> None:
    data = event["data"]
    title = data.get("task_title", "a task")
    recipients: dict[uuid.UUID, tuple[NotificationKind, str]] = {}
    if event["type"] == "comment.created":
        assignee = _uuid(data.get("assignee_id"))
        if assignee:
            recipients[assignee] = (NotificationKind.COMMENT, f"New comment on {title}")
        mentioned = data["comment"]["mentions"]
    else:
        mentioned = data.get("new_mentions", [])
    for raw in mentioned:
        if (uid := _uuid(raw)) is not None:
            recipients[uid] = (NotificationKind.MENTION, f"You were mentioned on {title}")
    await _notify(event, recipients)


@handles("task.created", "task.updated")
async def on_task_assignment(event: Event) -> None:
    data = event["data"]
    task = data["task"]
    if event["type"] == "task.created":
        assignee = _uuid(task.get("assignee_id"))
    else:
        change = data.get("changes", {}).get("assignee_id")
        assignee = _uuid(change.get("to")) if change else None
    if assignee:
        await _notify(
            event, {assignee: (NotificationKind.ASSIGNED, f"{task['key']} assigned to you: {task['title']}")}
        )
