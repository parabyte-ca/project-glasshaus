"""Custom field definitions and value validation."""

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from glasshaus.core import events
from glasshaus.core.authz import require_project
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, InvalidInput, NotFound
from glasshaus.core.rbac import Permission
from glasshaus.fields.models import CustomField, FieldType
from glasshaus.fields.schemas import FieldCreate, FieldRead, FieldUpdate
from glasshaus.identity.models import User
from glasshaus.tasks.models import Task

URL_RE = re.compile(r"^https?://[^\s]{1,2000}$")
MAX_TEXT = 5000


async def fields_for(ctx: ServiceContext, project_id: uuid.UUID) -> list[CustomField]:
    key = ("fields", project_id)
    if key not in ctx.cache:
        rows = await ctx.session.scalars(
            select(CustomField).where(CustomField.project_id == project_id).order_by(CustomField.position)
        )
        ctx.cache[key] = list(rows.all())
    cached: list[CustomField] = ctx.cache[key]
    return cached


def _expire_tasks(ctx: ServiceContext) -> None:
    """Bulk SQL updated task rows: drop stale in-memory copies (only tasks, so other objects stay loaded)."""
    for obj in list(ctx.session.identity_map.values()):
        if isinstance(obj, Task):
            ctx.session.expire(obj)


def _invalidate(ctx: ServiceContext, project_id: uuid.UUID) -> None:
    ctx.cache.pop(("fields", project_id), None)


async def list_fields(ctx: ServiceContext, project_id: uuid.UUID) -> list[FieldRead]:
    await require_project(ctx, project_id, Permission.PROJECT_READ)
    return [FieldRead.model_validate(f) for f in await fields_for(ctx, project_id)]


async def create_field(ctx: ServiceContext, project_id: uuid.UUID, data: FieldCreate) -> FieldRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    position = data.position
    if position is None:
        last = await ctx.session.scalar(
            select(func.max(CustomField.position)).where(CustomField.project_id == project_id)
        )
        position = (last or 0) + 1
    field = CustomField(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        name=data.name,
        type=data.type,
        description=data.description,
        required=data.required,
        options=[o.model_dump() for o in data.options],
        position=position,
    )
    ctx.session.add(field)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a field with this name already exists") from exc
    _invalidate(ctx, project_id)
    result = FieldRead.model_validate(field)
    events.emit(ctx, "field.created", "project", project_id, result)
    return result


async def _field(ctx: ServiceContext, project_id: uuid.UUID, field_id: uuid.UUID) -> CustomField:
    field = await ctx.session.get(CustomField, field_id)
    if field is None or field.project_id != project_id:
        raise NotFound("field not found")
    return field


async def update_field(
    ctx: ServiceContext, project_id: uuid.UUID, field_id: uuid.UUID, data: FieldUpdate
) -> FieldRead:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    field = await _field(ctx, project_id, field_id)
    changes = data.model_dump(exclude_unset=True)
    if "options" in changes:
        if field.type not in (FieldType.SELECT, FieldType.MULTI_SELECT):
            raise InvalidInput("options only apply to select and multi_select fields")
        if not changes["options"]:
            raise InvalidInput("select fields need at least one option")
        removed = {o["id"] for o in field.options} - {o["id"] for o in changes["options"]}
        if removed:
            await _clear_option_values(ctx, field, removed)
    for key, value in changes.items():
        setattr(field, key, value)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a field with this name already exists") from exc
    _invalidate(ctx, project_id)
    events.emit(ctx, "field.updated", "project", project_id, {"field_id": str(field_id), "changes": changes})
    return FieldRead.model_validate(field)


async def _clear_option_values(ctx: ServiceContext, field: CustomField, removed: set[str]) -> None:
    fid = str(field.id)
    if field.type == FieldType.SELECT:
        await ctx.session.execute(
            update(Task)
            .where(Task.project_id == field.project_id, Task.custom_fields[fid].astext.in_(removed))
            .values(custom_fields=Task.custom_fields.op("-")(fid), version=Task.version + 1)
            .execution_options(synchronize_session=False)
        )
    else:
        # Rebuild multi-select arrays without the removed option ids.
        await ctx.session.execute(
            text(
                "UPDATE tasks SET version = version + 1, "
                "custom_fields = jsonb_set(custom_fields, ARRAY[:fid], "
                "COALESCE((SELECT jsonb_agg(v) FROM jsonb_array_elements_text(custom_fields -> :fid) v "
                "WHERE v <> ALL(:removed)), '[]'::jsonb)) "
                "WHERE project_id = :pid AND custom_fields ? :fid"
            ),
            {"fid": fid, "removed": list(removed), "pid": field.project_id},
        )
    _expire_tasks(ctx)


async def delete_field(ctx: ServiceContext, project_id: uuid.UUID, field_id: uuid.UUID) -> None:
    await require_project(ctx, project_id, Permission.PROJECT_UPDATE)
    field = await _field(ctx, project_id, field_id)
    fid = str(field.id)
    await ctx.session.execute(
        update(Task)
        .where(Task.project_id == project_id, Task.custom_fields.has_key(fid))
        .values(custom_fields=Task.custom_fields.op("-")(fid), version=Task.version + 1)
        .execution_options(synchronize_session=False)
    )
    name = field.name
    await ctx.session.delete(field)
    _invalidate(ctx, project_id)
    _expire_tasks(ctx)
    events.emit(ctx, "field.deleted", "project", project_id, {"field_id": fid, "name": name})


# --------------------------------------------------------------------------- values


async def _coerce(ctx: ServiceContext, field: CustomField, value: Any) -> Any:
    name = field.name
    match field.type:
        case FieldType.TEXT:
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise InvalidInput(f"{name}: expected text up to {MAX_TEXT} characters")
            return value
        case FieldType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InvalidInput(f"{name}: expected a number")
            return value
        case FieldType.DATE:
            try:
                return date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise InvalidInput(f"{name}: expected a date (YYYY-MM-DD)") from exc
        case FieldType.CHECKBOX:
            if not isinstance(value, bool):
                raise InvalidInput(f"{name}: expected true or false")
            return value
        case FieldType.URL:
            if not isinstance(value, str) or not URL_RE.match(value):
                raise InvalidInput(f"{name}: expected an http(s) URL")
            return value
        case FieldType.SELECT:
            ids = {o["id"] for o in field.options}
            if value not in ids:
                raise InvalidInput(f"{name}: unknown option")
            return value
        case FieldType.MULTI_SELECT:
            ids = {o["id"] for o in field.options}
            if not isinstance(value, list) or not all(isinstance(v, str) and v in ids for v in value):
                raise InvalidInput(f"{name}: expected a list of option ids")
            return sorted(set(value))
        case FieldType.USER:
            try:
                user_id = uuid.UUID(str(value))
            except ValueError as exc:
                raise InvalidInput(f"{name}: expected a user id") from exc
            if await ctx.session.get(User, user_id) is None:
                raise InvalidInput(f"{name}: user not found")
            return str(user_id)
    raise InvalidInput(f"{name}: unsupported field type")  # pragma: no cover


async def merge_values(
    ctx: ServiceContext,
    project_id: uuid.UUID,
    current: dict[str, Any],
    patch: dict[str, Any],
    *,
    creating: bool = False,
) -> dict[str, Any]:
    """Validate ``patch`` (field id -> value, null clears) against the project's fields and merge it."""
    fields = {str(f.id): f for f in await fields_for(ctx, project_id)}
    merged = dict(current)
    for key, value in patch.items():
        field = fields.get(key)
        if field is None:
            raise InvalidInput(f"unknown custom field {key}")
        if value is None or value == [] or value == "":
            if field.required:
                raise InvalidInput(f"{field.name} is required")
            merged.pop(key, None)
        else:
            merged[key] = await _coerce(ctx, field, value)
    if creating:
        missing = [f.name for fid, f in fields.items() if f.required and fid not in merged]
        if missing:
            raise InvalidInput(f"required fields missing: {', '.join(missing)}")
    return merged
