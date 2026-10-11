"""My team (managers) and the Microsoft Graph directory sync (org admins)."""

import uuid

from fastapi import APIRouter, Query

from glasshaus.api.deps import Ctx, CurrentActor
from glasshaus.people import graph
from glasshaus.people import service as people
from glasshaus.people.schemas import DirectorySyncRead, DirectorySyncWrite, TeamRead, TeamTasks

router = APIRouter(tags=["team"])


@router.get("/team", response_model=TeamRead, summary="The people who report to you, with their work")
async def my_team(
    ctx: Ctx,
    everyone: bool = Query(False, description="Include everyone further down, not only direct reports."),
) -> TeamRead:
    return await people.my_team(ctx, everyone=everyone)


@router.get(
    "/team/{person_id}/tasks",
    response_model=TeamTasks,
    summary="One of your reports' open tasks, or those finished in the last 30 days (audited)",
)
async def report_tasks(
    person_id: uuid.UUID, ctx: Ctx, done: bool = Query(False, description="Finished work instead.")
) -> TeamTasks:
    return await people.report_tasks(ctx, person_id, done=done)


@router.get(
    "/admin/directory-sync",
    response_model=DirectorySyncRead,
    summary="Microsoft Graph directory sync settings",
)
async def get_directory_sync(ctx: Ctx) -> DirectorySyncRead:
    return await graph.get_settings(ctx)


@router.put(
    "/admin/directory-sync",
    response_model=DirectorySyncRead,
    summary="Set up or change the Microsoft Graph directory sync",
)
async def update_directory_sync(ctx: Ctx, data: DirectorySyncWrite) -> DirectorySyncRead:
    return await graph.update_settings(ctx, data)


@router.post(
    "/admin/directory-sync/run",
    response_model=DirectorySyncRead,
    summary="Sync managers, job titles and departments from Microsoft Graph now",
)
async def run_directory_sync(actor: CurrentActor) -> DirectorySyncRead:
    return await graph.sync_now(actor)
