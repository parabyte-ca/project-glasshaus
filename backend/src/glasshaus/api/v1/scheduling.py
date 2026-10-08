import uuid
from datetime import date

from fastapi import APIRouter, status

from glasshaus.api.deps import Ctx
from glasshaus.scheduling import service as scheduling
from glasshaus.scheduling.schemas import (
    BaselineCreate,
    BaselineRead,
    BaselineVariance,
    DependencyCreate,
    DependencyRead,
    DependencyResult,
    DependencyUpdate,
    RescheduleResult,
    ScheduleRead,
    ScheduleWarning,
    TaskDependencies,
)

router = APIRouter(tags=["scheduling"])


@router.get(
    "/projects/{project_id}/dependencies",
    response_model=list[DependencyRead],
    summary="All task dependencies in a project",
)
async def list_dependencies(project_id: uuid.UUID, ctx: Ctx) -> list[DependencyRead]:
    return await scheduling.list_dependencies(ctx, project_id)


@router.get(
    "/tasks/{ref}/dependencies",
    response_model=TaskDependencies,
    summary="A task's predecessors and successors",
)
async def get_task_dependencies(ref: str, ctx: Ctx) -> TaskDependencies:
    return await scheduling.task_dependencies(ctx, ref)


@router.post(
    "/dependencies",
    response_model=DependencyResult,
    status_code=status.HTTP_201_CREATED,
    summary="Link two tasks (FS, SS, FF, SF with lag or lead)",
)
async def create_dependency(body: DependencyCreate, ctx: Ctx) -> DependencyResult:
    return await scheduling.create_dependency(ctx, body)


@router.patch("/dependencies/{dependency_id}", response_model=DependencyResult, summary="Change type or lag")
async def update_dependency(dependency_id: uuid.UUID, body: DependencyUpdate, ctx: Ctx) -> DependencyResult:
    return await scheduling.update_dependency(ctx, dependency_id, body)


@router.delete(
    "/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a dependency"
)
async def delete_dependency(dependency_id: uuid.UUID, ctx: Ctx) -> None:
    await scheduling.delete_dependency(ctx, dependency_id)


@router.get(
    "/projects/{project_id}/schedule",
    response_model=ScheduleRead,
    summary="Critical path: early/late dates, slack and critical tasks",
)
async def get_schedule(project_id: uuid.UUID, ctx: Ctx) -> ScheduleRead:
    return await scheduling.get_schedule(ctx, project_id)


@router.post(
    "/projects/{project_id}/reschedule",
    response_model=RescheduleResult,
    summary="Move tasks later to satisfy every dependency (dry_run=true, the default, only previews)",
)
async def reschedule_project(project_id: uuid.UUID, ctx: Ctx, dry_run: bool = True) -> RescheduleResult:
    return await scheduling.reschedule(ctx, project_id, dry_run=dry_run)


@router.get(
    "/projects/{project_id}/schedule/warnings",
    response_model=list[ScheduleWarning],
    summary="Slip warnings: overdue, violated dependencies, behind baseline",
)
async def get_schedule_warnings(
    project_id: uuid.UUID, ctx: Ctx, today: date | None = None
) -> list[ScheduleWarning]:
    return await scheduling.schedule_warnings(ctx, project_id, today=today)


@router.get("/projects/{project_id}/baselines", response_model=list[BaselineRead], summary="List baselines")
async def list_baselines(project_id: uuid.UUID, ctx: Ctx) -> list[BaselineRead]:
    return await scheduling.list_baselines(ctx, project_id)


@router.post(
    "/projects/{project_id}/baselines",
    response_model=BaselineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Snapshot every task's planned dates",
)
async def create_baseline(project_id: uuid.UUID, body: BaselineCreate, ctx: Ctx) -> BaselineRead:
    return await scheduling.create_baseline(ctx, project_id, body)


@router.get(
    "/baselines/{baseline_id}/variance",
    response_model=BaselineVariance,
    summary="Compare current dates with a baseline",
)
async def get_baseline_variance(baseline_id: uuid.UUID, ctx: Ctx) -> BaselineVariance:
    return await scheduling.baseline_variance(ctx, baseline_id)


@router.delete(
    "/baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a baseline"
)
async def delete_baseline(baseline_id: uuid.UUID, ctx: Ctx) -> None:
    await scheduling.delete_baseline(ctx, baseline_id)
