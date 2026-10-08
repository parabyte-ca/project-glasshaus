import uuid

from fastapi import APIRouter, Query, status

from glasshaus.api.deps import Ctx
from glasshaus.collab import service as collab
from glasshaus.collab.schemas import (
    ActivityItem,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    NotificationRead,
    NotificationsMarkRead,
)
from glasshaus.core.schemas import Page, Schema
from glasshaus.tasks import service as tasks

router = APIRouter()


class UnreadCount(Schema):
    unread: int


class MarkedRead(Schema):
    updated: int


@router.get(
    "/tasks/{ref}/comments", response_model=list[CommentRead], tags=["comments"], summary="List comments"
)
async def list_comments(ref: str, ctx: Ctx) -> list[CommentRead]:
    return await collab.list_comments(ctx, await tasks.resolve_ref(ctx, ref))


@router.post(
    "/tasks/{ref}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["comments"],
    summary="Comment on a task (supports @mentions)",
)
async def create_comment(ref: str, body: CommentCreate, ctx: Ctx) -> CommentRead:
    return await collab.create_comment(ctx, await tasks.resolve_ref(ctx, ref), body)


@router.patch(
    "/comments/{comment_id}", response_model=CommentRead, tags=["comments"], summary="Edit your comment"
)
async def update_comment(comment_id: uuid.UUID, body: CommentUpdate, ctx: Ctx) -> CommentRead:
    return await collab.update_comment(ctx, comment_id, body)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["comments"],
    summary="Delete a comment",
)
async def delete_comment(comment_id: uuid.UUID, ctx: Ctx) -> None:
    await collab.delete_comment(ctx, comment_id)


@router.get(
    "/notifications",
    response_model=Page[NotificationRead],
    tags=["notifications"],
    summary="Your notifications, newest first",
)
async def list_notifications(
    ctx: Ctx, unread_only: bool = False, limit: int = Query(50, ge=1, le=200), cursor: str | None = None
) -> Page[NotificationRead]:
    return await collab.list_notifications(ctx, unread_only=unread_only, limit=limit, cursor=cursor)


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCount,
    tags=["notifications"],
    summary="Number of unread notifications",
)
async def get_unread_count(ctx: Ctx) -> UnreadCount:
    return UnreadCount(unread=await collab.unread_count(ctx))


@router.post(
    "/notifications/read",
    response_model=MarkedRead,
    tags=["notifications"],
    summary="Mark notifications as read",
)
async def mark_notifications_read(body: NotificationsMarkRead, ctx: Ctx) -> MarkedRead:
    return MarkedRead(updated=await collab.mark_read(ctx, body.ids))


@router.get(
    "/activity",
    response_model=Page[ActivityItem],
    tags=["activity"],
    summary="Activity feed for a task, a project, or everything you can see",
)
async def list_activity(
    ctx: Ctx,
    task: str | None = Query(None, description="Task id or reference such as WEB-12"),
    project_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> Page[ActivityItem]:
    task_id = await tasks.resolve_ref(ctx, task) if task else None
    return await collab.activity(ctx, task_id=task_id, project_id=project_id, limit=limit, cursor=cursor)
