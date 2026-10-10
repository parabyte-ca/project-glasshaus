import uuid

from fastapi import APIRouter

from glasshaus.api.deps import Ctx
from glasshaus.imports import service as imports
from glasshaus.imports.schemas import ImportRequest, ImportResult

router = APIRouter(prefix="/projects/{project_id}/import", tags=["import"])


@router.post(
    "",
    response_model=ImportResult,
    summary="Import tasks from spreadsheet rows",
    description=(
        "Rows come from a CSV or Excel file (or another tool's export), already mapped to Glasshaus fields. "
        "Rows with an ID are remembered, so importing the same file again updates them. Use `dry_run` to "
        "check first. People are matched by email (or exact name); imported tasks don't notify anyone."
    ),
)
async def import_rows(project_id: uuid.UUID, body: ImportRequest, ctx: Ctx) -> ImportResult:
    return await imports.import_rows(ctx, project_id, body)
