from fastapi import APIRouter

from glasshaus.api.errors import PROBLEM_RESPONSES
from glasshaus.api.v1 import (
    admin,
    ai,
    auth,
    automation,
    collab,
    fields,
    goals,
    insights,
    integrations,
    oauth,
    projects,
    scheduling,
    sso,
    tasks,
    timetracking,
    users,
    views,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1", responses=PROBLEM_RESPONSES)
for module in (
    auth,
    users,
    workspaces,
    projects,
    fields,
    views,
    tasks,
    scheduling,
    collab,
    automation,
    timetracking,
    insights,
    goals,
    oauth,
    admin,
    ai,
    sso,
    integrations,
):
    api_router.include_router(module.router)
