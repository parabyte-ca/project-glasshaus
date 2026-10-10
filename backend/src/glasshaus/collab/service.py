"""Comments, notifications and activity feed."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, tuple_, update

from glasshaus.collab.mentions import extract_mentions
from glasshaus.collab.models import Comment, Notification, NotificationKind
from glasshaus.collab.schemas import (
    ActivityItem,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    NotificationRead,
)
from glasshaus.core import events
from glasshaus.core.authz import require_project, require_scope, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.events import envelope
from glasshaus.core.models import DomainEventRecord
from glasshaus.core.rbac import Permission
from glasshaus.core.schemas import Page, decode_cursor, decode_keyset, encode_cursor, encode_keyset
from glasshaus.projects.models import Project
from glasshaus.tasks.models import Task


async def _task(ctx: ServiceContext, task_id: uuid.UUID, permission: Permission) -> Task:
    task = await ctx.session.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise NotFound("task not found")
    try:
        await require_project(ctx, task.project_id, permission)
    except NotFound:
        raise NotFound("task not found") from None
    return task


# --------------------------------------------------------------------------- comments


async def list_comments(ctx: ServiceContext, task_id: uuid.UUID) -> list[CommentRead]:
    await _task(ctx, task_id, Permission.TASK_READ)
    rows = await ctx.session.scalars(
        select(Comment)
        .where(Comment.task_id == task_id, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at, Comment.id)
    )
    return [CommentRead.model_validate(c) for c in rows.all()]


async def create_comment(ctx: ServiceContext, task_id: uuid.UUID, data: CommentCreate) -> CommentRead:
    task = await _task(ctx, task_id, Permission.COMMENT_CREATE)
    comment = Comment(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        task_id=task.id,
        author_id=ctx.actor.user_id,
        body=data.body,
        mentions=await extract_mentions(ctx, data.body),
    )
    ctx.session.add(comment)
    await ctx.session.flush()
    result = CommentRead.model_validate(comment)
    events.emit(
        ctx,
        "comment.created",
        "task",
        task.id,
        {
            # Comment text stays out of the event history (kept for years, shown in activity, sent to
            # webhooks); consumers that need it read the comment, so a deleted comment is gone everywhere.
            "comment": result.model_dump(mode="json", exclude={"body"}),
            "task_title": task.title,
            "assignee_id": task.assignee_id,
        },
        project_id=task.project_id,
    )
    return result


async def _own_comment(ctx: ServiceContext, comment_id: uuid.UUID) -> tuple[Comment, Task]:
    comment = await ctx.session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise NotFound("comment not found")
    task = await _task(ctx, comment.task_id, Permission.TASK_READ)
    return comment, task


async def update_comment(ctx: ServiceContext, comment_id: uuid.UUID, data: CommentUpdate) -> CommentRead:
    comment, task = await _own_comment(ctx, comment_id)
    require_scope(ctx, Permission.COMMENT_CREATE)
    if comment.author_id != ctx.actor.user_id:
        raise PermissionDenied("only the author can edit a comment")
    previous = set(comment.mentions)
    comment.body = data.body
    comment.mentions = await extract_mentions(ctx, data.body)
    comment.edited_at = datetime.now(UTC)
    await ctx.session.flush()
    result = CommentRead.model_validate(comment)
    events.emit(
        ctx,
        "comment.updated",
        "task",
        task.id,
        {
            "comment": result.model_dump(mode="json", exclude={"body"}),
            "task_title": task.title,
            "new_mentions": [str(m) for m in set(comment.mentions) - previous],
        },
        project_id=task.project_id,
    )
    return result


async def delete_comment(ctx: ServiceContext, comment_id: uuid.UUID) -> None:
    comment, task = await _own_comment(ctx, comment_id)
    if comment.author_id != ctx.actor.user_id:
        await require_project(ctx, task.project_id, Permission.PROJECT_UPDATE)  # moderators: project admins
    else:
        require_scope(ctx, Permission.COMMENT_CREATE)
    comment.deleted_at = datetime.now(UTC)
    events.emit(
        ctx, "comment.deleted", "task", task.id, {"comment_id": str(comment.id)}, project_id=task.project_id
    )


# --------------------------------------------------------------------------- notifications


async def list_notifications(
    ctx: ServiceContext, *, unread_only: bool = False, limit: int = 50, cursor: str | None = None
) -> Page[NotificationRead]:
    if ctx.actor.user_id is None:
        raise PermissionDenied("a user principal is required")
    require_scope(ctx, Permission.TASK_READ)
    offset = decode_cursor(cursor)
    stmt = select(Notification).where(Notification.user_id == ctx.actor.user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = list(
        (
            await ctx.session.scalars(
                stmt.order_by(Notification.created_at.desc(), Notification.id).offset(offset).limit(limit + 1)
            )
        ).all()
    )
    more = len(rows) > limit
    return Page[NotificationRead](
        items=[NotificationRead.model_validate(n) for n in rows[:limit]],
        next_cursor=encode_cursor(offset + limit) if more else None,
    )


async def unread_count(ctx: ServiceContext) -> int:
    if ctx.actor.user_id is None:
        return 0
    count = await ctx.session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == ctx.actor.user_id, Notification.read_at.is_(None))
    )
    return count or 0


async def mark_read(ctx: ServiceContext, ids: list[uuid.UUID] | None) -> int:
    if ctx.actor.user_id is None:
        raise PermissionDenied("a user principal is required")
    stmt = (
        update(Notification)
        .where(Notification.user_id == ctx.actor.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = await ctx.session.execute(stmt)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- activity


def _public(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if k != "tenant_id"}


async def activity(
    ctx: ServiceContext,
    *,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> Page[ActivityItem]:
    """Recent domain events, newest first, limited to projects the actor can read."""
    if limit < 1 or limit > 200:
        raise InvalidInput("limit must be between 1 and 200")
    require_scope(ctx, Permission.PROJECT_READ)
    position = decode_keyset(cursor)
    stmt = select(DomainEventRecord)
    if task_id is not None:
        task = await _task(ctx, task_id, Permission.TASK_READ)
        stmt = stmt.where(
            DomainEventRecord.aggregate_type == "task", DomainEventRecord.aggregate_id == task.id
        )
    elif project_id is not None:
        await require_project(ctx, project_id, Permission.PROJECT_READ)
        stmt = stmt.where(DomainEventRecord.project_id == project_id)
    else:
        visible = select(Project.id).where(visible_projects_clause(ctx))
        stmt = stmt.where(
            or_(
                DomainEventRecord.project_id.in_(visible),
                and_(DomainEventRecord.project_id.is_(None), DomainEventRecord.actor_id == ctx.actor.user_id),
            )
        )
    # Keyset paging (newest first): deep pages cost the same as the first.
    if isinstance(position, tuple):
        stmt = stmt.where(tuple_(DomainEventRecord.occurred_at, DomainEventRecord.id) < tuple_(*position))
    elif isinstance(position, int):
        stmt = stmt.offset(position)
    rows = list(
        (
            await ctx.session.scalars(
                stmt.order_by(DomainEventRecord.occurred_at.desc(), DomainEventRecord.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
    )
    more = len(rows) > limit
    page = rows[:limit]
    return Page[ActivityItem](
        items=[ActivityItem.model_validate(_public(envelope(r))) for r in page],
        next_cursor=encode_keyset(page[-1].occurred_at, page[-1].id) if more else None,
    )


async def notify_users(
    ctx: ServiceContext,
    user_ids: list[uuid.UUID],
    *,
    kind: NotificationKind,
    title: str,
    link: str | None = None,
    event_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Notify people about something that is not a task (a report alert, a backup problem).

    With ``event_id`` each person is notified once for it, so a repeated check never piles up
    duplicates. Returns the people who got a new notification. Callers check access themselves.
    """
    from sqlalchemy.dialects.postgresql import insert

    event = event_id or uuid.uuid4()
    created: list[uuid.UUID] = []
    for user_id in dict.fromkeys(user_ids):
        stmt = (
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                tenant_id=ctx.tenant_id,
                user_id=user_id,
                kind=kind,
                event_id=event,
                title=title[:300],
                link=link,
            )
            .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
        )
        if (await ctx.session.execute(stmt)).rowcount:  # type: ignore[attr-defined]
            created.append(user_id)
    if created:
        from glasshaus.realtime import publish_user_signal

        await publish_user_signal(ctx.tenant_id, [str(u) for u in created], "notification.created")
    return created
