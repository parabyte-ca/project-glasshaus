import uuid

from fastapi import APIRouter, status

from glasshaus.api.deps import Ctx
from glasshaus.fields import service as fields
from glasshaus.fields.schemas import FieldCreate, FieldRead, FieldUpdate

router = APIRouter(prefix="/projects/{project_id}/fields", tags=["custom fields"])


@router.get("", response_model=list[FieldRead], summary="List a project's custom fields")
async def list_fields(project_id: uuid.UUID, ctx: Ctx) -> list[FieldRead]:
    return await fields.list_fields(ctx, project_id)


@router.post("", response_model=FieldRead, status_code=status.HTTP_201_CREATED, summary="Add a custom field")
async def create_field(project_id: uuid.UUID, body: FieldCreate, ctx: Ctx) -> FieldRead:
    return await fields.create_field(ctx, project_id, body)


@router.patch("/{field_id}", response_model=FieldRead, summary="Rename a field or change its options")
async def update_field(project_id: uuid.UUID, field_id: uuid.UUID, body: FieldUpdate, ctx: Ctx) -> FieldRead:
    return await fields.update_field(ctx, project_id, field_id, body)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a field and its values")
async def delete_field(project_id: uuid.UUID, field_id: uuid.UUID, ctx: Ctx) -> None:
    await fields.delete_field(ctx, project_id, field_id)
