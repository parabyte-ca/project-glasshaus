from fastapi import APIRouter

from glasshaus.api.errors import PROBLEM_RESPONSES
from glasshaus.api.v1 import auth, projects, tasks, users, workspaces

api_router = APIRouter(prefix="/api/v1", responses=PROBLEM_RESPONSES)
for module in (auth, users, workspaces, projects, tasks):
    api_router.include_router(module.router)
