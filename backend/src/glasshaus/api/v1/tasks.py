import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status

from glasshaus.api.deps import Ctx
from glasshaus.core.errors import InvalidInput
from glasshaus.core.schemas import Page, Schema
from glasshaus.projects.schemas import DeletePreview
from glasshaus.tasks import service as tasks
from glasshaus.tasks.schemas import BulkResult, TaskBulkUpdate, TaskCreate, TaskQuery, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskIds(Schema):
    task_ids: list[uuid.UUID]


def _etag(task: TaskRead) -> str:
    return f'W/"{task.version}"'


def _if_match_version(if_match: str | None) -> int | None:
    if not if_match:
        return None
    try:
        return int(if_match.removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise InvalidInput("If-Match must be an ETag returned by this API") from exc


@router.get("", response_model=Page[TaskRead], summary="Search and list tasks")
async def list_tasks(ctx: Ctx, query: Annotated[TaskQuery, Query()]) -> Page[TaskRead]:
    return await tasks.list_tasks(ctx, query)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED, summary="Create a task")
async def create_task(body: TaskCreate, ctx: Ctx, response: Response) -> TaskRead:
    task = await tasks.create_task(ctx, body)
    response.headers["ETag"] = _etag(task)
    return task


@router.post("/bulk-update", response_model=BulkResult, summary="Apply one change to many tasks")
async def bulk_update_tasks(body: TaskBulkUpdate, ctx: Ctx) -> BulkResult:
    return await tasks.bulk_update(ctx, body)


@router.post(
    "/bulk-delete",
    response_model=list[DeletePreview],
    summary="Delete tasks and their subtasks (dry_run=true, the default, only previews)",
)
async def bulk_delete_tasks(body: TaskIds, ctx: Ctx, dry_run: bool = True) -> list[DeletePreview]:
    return await tasks.delete_tasks(ctx, body.task_ids, dry_run=dry_run)


@router.get("/{ref}", response_model=TaskRead, summary="Get a task by id or reference (e.g. WEB-12)")
async def get_task(ref: str, ctx: Ctx, response: Response) -> TaskRead:
    task = await tasks.get_task(ctx, await tasks.resolve_ref(ctx, ref))
    response.headers["ETag"] = _etag(task)
    return task


@router.patch("/{ref}", response_model=TaskRead, summary="Update a task (supports If-Match)")
async def update_task(
    ref: str, body: TaskUpdate, ctx: Ctx, response: Response, if_match: Annotated[str | None, Header()] = None
) -> TaskRead:
    if body.expected_version is None and (version := _if_match_version(if_match)) is not None:
        body = body.model_copy(update={"expected_version": version})
    task = await tasks.update_task(ctx, await tasks.resolve_ref(ctx, ref), body)
    response.headers["ETag"] = _etag(task)
    return task


@router.delete("/{ref}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a task and its subtasks")
async def delete_task(ref: str, ctx: Ctx) -> None:
    await tasks.delete_tasks(ctx, [await tasks.resolve_ref(ctx, ref)], dry_run=False)


@router.post("/{ref}/restore", response_model=TaskRead, summary="Restore a deleted task")
async def restore_task(ref: str, ctx: Ctx) -> TaskRead:
    return await tasks.restore_task(ctx, await tasks.resolve_ref(ctx, ref))


@router.get("/{ref}/permissions", response_model=list[str], summary="Your permissions on a task")
async def get_task_permissions(ref: str, ctx: Ctx) -> list[str]:
    return await tasks.can(ctx, await tasks.resolve_ref(ctx, ref))
