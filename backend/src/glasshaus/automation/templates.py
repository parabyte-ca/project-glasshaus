"""Project templates: snapshot a project's structure, then create new projects from it.

A snapshot keeps statuses, custom fields, shared views, tasks (dates as offsets), dependencies,
automation rules and recurring tasks. People (assignees, members) and comments are not copied.
Every internal id is remapped on instantiation.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from glasshaus.automation.models import AutomationRule, ProjectTemplate, RecurringTask
from glasshaus.automation.schemas import (
    RecurringCreate,
    RuleCreate,
    TemplateCreate,
    TemplateInstantiate,
    TemplateRead,
    TemplateSummary,
)
from glasshaus.core.authz import require_project
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import Conflict, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.projects.schemas import ProjectDetail

SNAPSHOT_VERSION = 1
MAX_TEMPLATE_TASKS = 2000


def _summary(snapshot: dict[str, Any]) -> TemplateSummary:
    return TemplateSummary(
        statuses=len(snapshot.get("statuses", [])),
        fields=len(snapshot.get("fields", [])),
        views=len(snapshot.get("views", [])),
        tasks=len(snapshot.get("tasks", [])),
        dependencies=len(snapshot.get("dependencies", [])),
        rules=len(snapshot.get("rules", [])),
        recurring=len(snapshot.get("recurring", [])),
    )


def _read(t: ProjectTemplate) -> TemplateRead:
    return TemplateRead(
        id=t.id,
        name=t.name,
        description=t.description,
        created_by=t.created_by,
        created_at=t.created_at,
        summary=_summary(t.snapshot),
    )


def remap(value: Any, ids: dict[str, str]) -> Any:
    """Replace every old id (in strings and dict keys, including ``cf:<id>``) with its new id."""
    if isinstance(value, dict):
        return {remap(k, ids): remap(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, ids) for v in value]
    if isinstance(value, str):
        for old, new in ids.items():
            if old in value:
                value = value.replace(old, new)
        return value
    return value


async def snapshot_project(
    ctx: ServiceContext, project_id: uuid.UUID, *, tasks: bool, automations: bool
) -> dict[str, Any]:
    from glasshaus.fields.models import CustomField
    from glasshaus.projects.models import ProjectStatus
    from glasshaus.scheduling.models import TaskDependency
    from glasshaus.tasks.models import Task
    from glasshaus.views.models import SavedView

    statuses = (
        await ctx.session.scalars(
            select(ProjectStatus)
            .where(ProjectStatus.project_id == project_id)
            .order_by(ProjectStatus.position)
        )
    ).all()
    fields = (
        await ctx.session.scalars(
            select(CustomField).where(CustomField.project_id == project_id).order_by(CustomField.position)
        )
    ).all()
    views = (
        await ctx.session.scalars(
            select(SavedView)
            .where(SavedView.project_id == project_id, SavedView.shared.is_(True))
            .order_by(SavedView.position)
        )
    ).all()
    snap: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "statuses": [
            {
                "id": str(s.id),
                "name": s.name,
                "category": s.category.value,
                "color": s.color,
                "position": s.position,
            }
            for s in statuses
        ],
        "fields": [
            {
                "id": str(f.id),
                "name": f.name,
                "type": f.type.value,
                "description": f.description,
                "required": f.required,
                "options": f.options,
                "position": f.position,
            }
            for f in fields
        ],
        "views": [
            {"name": v.name, "kind": v.kind.value, "config": v.config, "position": v.position} for v in views
        ],
        "tasks": [],
        "dependencies": [],
        "rules": [],
        "recurring": [],
    }
    if tasks:
        rows = (
            await ctx.session.scalars(
                select(Task)
                .where(Task.project_id == project_id, Task.deleted_at.is_(None))
                .order_by(Task.number)
                .limit(MAX_TEMPLATE_TASKS)
            )
        ).all()
        dated = [d for t in rows for d in (t.start_date, t.due_date) if d]
        anchor = min(dated) if dated else None

        def offset(d: date | None) -> int | None:
            return (d - anchor).days if d and anchor else None

        kept = {t.id for t in rows}
        snap["tasks"] = [
            {
                "id": str(t.id),
                "parent_id": str(t.parent_id) if t.parent_id in kept else None,
                "title": t.title,
                "description": t.description,
                "status_id": str(t.status_id),
                "priority": t.priority.value,
                "start_offset": offset(t.start_date),
                "due_offset": offset(t.due_date),
                "estimate_minutes": t.estimate_minutes,
                "tags": t.tags,
                "custom_fields": t.custom_fields,
                "position": t.position,
            }
            for t in rows
        ]
        deps = (
            await ctx.session.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id))
        ).all()
        snap["dependencies"] = [
            {
                "predecessor": str(d.predecessor_id),
                "successor": str(d.successor_id),
                "type": d.type.value,
                "lag_days": d.lag_days,
            }
            for d in deps
            if d.predecessor_id in kept and d.successor_id in kept
        ]
    if automations:
        rules = (
            await ctx.session.scalars(
                select(AutomationRule)
                .where(AutomationRule.project_id == project_id)
                .order_by(AutomationRule.created_at)
            )
        ).all()
        snap["rules"] = [
            {
                "name": r.name,
                "enabled": r.enabled,
                "trigger": r.trigger,
                "conditions": r.conditions,
                "actions": r.actions,
                "run_on_automation": r.run_on_automation,
            }
            for r in rules
        ]
        recurring = (
            await ctx.session.scalars(select(RecurringTask).where(RecurringTask.project_id == project_id))
        ).all()
        snap["recurring"] = [
            {"enabled": r.enabled, "template": {**r.template, "assignee_id": None}, "schedule": r.schedule}
            for r in recurring
        ]
    return snap


async def list_templates(ctx: ServiceContext) -> list[TemplateRead]:
    if ctx.actor.org_role == OrgRole.GUEST:
        return []
    rows = await ctx.session.scalars(select(ProjectTemplate).order_by(ProjectTemplate.name))
    return [_read(t) for t in rows.all()]


async def _template(ctx: ServiceContext, template_id: uuid.UUID) -> ProjectTemplate:
    template = await ctx.session.get(ProjectTemplate, template_id)
    if template is None or ctx.actor.org_role == OrgRole.GUEST:
        raise NotFound("template not found")
    return template


async def get_template(ctx: ServiceContext, template_id: uuid.UUID) -> TemplateRead:
    return _read(await _template(ctx, template_id))


async def create_template(ctx: ServiceContext, data: TemplateCreate) -> TemplateRead:
    await require_project(ctx, data.project_id, Permission.PROJECT_UPDATE)
    if await ctx.session.scalar(select(ProjectTemplate.id).where(ProjectTemplate.name == data.name)):
        raise Conflict(f"a template named {data.name!r} already exists")
    snapshot = await snapshot_project(
        ctx, data.project_id, tasks=data.include_tasks, automations=data.include_automations
    )
    template = ProjectTemplate(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=data.name,
        description=data.description,
        created_by=ctx.actor.user_id,
        snapshot=snapshot,
    )
    ctx.session.add(template)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict(f"a template named {data.name!r} already exists") from exc
    return _read(template)


async def delete_template(ctx: ServiceContext, template_id: uuid.UUID) -> None:
    template = await _template(ctx, template_id)
    if template.created_by != ctx.actor.user_id and not ctx.actor.is_org_admin:
        raise PermissionDenied("only the creator or an organization admin can delete a template")
    await ctx.session.delete(template)
    await ctx.session.flush()


async def instantiate(
    ctx: ServiceContext, template_id: uuid.UUID, data: TemplateInstantiate
) -> ProjectDetail:
    from glasshaus.automation import service as automation
    from glasshaus.fields import service as fields
    from glasshaus.fields.schemas import FieldCreate, FieldUpdate
    from glasshaus.projects import service as projects
    from glasshaus.projects.schemas import ProjectCreate, StatusCreate, StatusUpdate
    from glasshaus.scheduling import service as scheduling
    from glasshaus.scheduling.schemas import DependencyCreate
    from glasshaus.tasks import service as tasks
    from glasshaus.tasks.schemas import TaskCreate
    from glasshaus.views import service as views
    from glasshaus.views.schemas import ViewConfig, ViewCreate

    template = await _template(ctx, template_id)
    snap = template.snapshot
    project = await projects.create_project(
        ctx,
        ProjectCreate(
            workspace_id=data.workspace_id,
            key=data.key,
            name=data.name,
            description=template.description if data.description is None else data.description,
        ),
    )
    pid = project.id
    ids: dict[str, str] = {}

    # Statuses: reuse defaults with the same name, add the rest, then drop unused defaults.
    defaults = {s.name: s for s in project.statuses}
    wanted = {s["name"] for s in snap["statuses"]}
    for s in snap["statuses"]:
        if s["name"] in defaults:
            current = defaults[s["name"]]
            await projects.update_status(
                ctx,
                pid,
                current.id,
                StatusUpdate(category=s["category"], color=s["color"], position=s["position"]),
            )
            ids[s["id"]] = str(current.id)
        else:
            created = await projects.create_status(
                ctx,
                pid,
                StatusCreate(
                    name=s["name"], category=s["category"], color=s["color"], position=s["position"]
                ),
            )
            ids[s["id"]] = str(created.id)
    for name, status in defaults.items():
        if wanted and name not in wanted:
            await projects.delete_status(ctx, pid, status.id, replacement_id=None)

    for f in snap["fields"]:
        created_field = await fields.create_field(
            ctx,
            pid,
            FieldCreate(
                name=f["name"],
                type=f["type"],
                description=f["description"],
                required=False,  # required is restored after tasks exist, so copies never fail validation
                options=f["options"],
                position=f["position"],
            ),
        )
        ids[f["id"]] = str(created_field.id)

    for v in snap["views"]:
        await views.create_view(
            ctx,
            pid,
            ViewCreate(
                name=v["name"],
                kind=v["kind"],
                shared=True,
                config=ViewConfig.model_validate(remap(v["config"], ids)),
                position=v["position"],
            ),
        )

    start = data.start_date or datetime.now(UTC).date()

    def shift(days: int | None) -> date | None:
        return start + timedelta(days=days) if days is not None else None

    pending = list(snap["tasks"])
    while pending:  # parents before children
        progressed = False
        for t in list(pending):
            if t["parent_id"] and t["parent_id"] not in ids:
                continue
            created_task = await tasks.create_task(
                ctx,
                TaskCreate(
                    project_id=pid,
                    title=t["title"],
                    description=t["description"],
                    status_id=uuid.UUID(ids[t["status_id"]]) if t["status_id"] in ids else None,
                    priority=t["priority"],
                    parent_id=uuid.UUID(ids[t["parent_id"]]) if t["parent_id"] else None,
                    start_date=shift(t["start_offset"]),
                    due_date=shift(t["due_offset"]),
                    estimate_minutes=t["estimate_minutes"],
                    tags=t["tags"],
                    custom_fields={
                        k: v for k, v in remap(t["custom_fields"], ids).items() if k in ids.values()
                    },
                    position=t["position"],
                ),
            )
            ids[t["id"]] = str(created_task.id)
            pending.remove(t)
            progressed = True
        if not progressed:  # orphaned parent reference: create the rest at top level
            for t in pending:
                t["parent_id"] = None

    for d in snap["dependencies"]:
        if d["predecessor"] in ids and d["successor"] in ids:
            await scheduling.create_dependency(
                ctx,
                DependencyCreate(
                    predecessor=ids[d["predecessor"]],
                    successor=ids[d["successor"]],
                    type=d["type"],
                    lag_days=d["lag_days"],
                ),
            )

    for f in snap["fields"]:
        if f["required"]:
            await fields.update_field(ctx, pid, uuid.UUID(ids[f["id"]]), FieldUpdate(required=True))

    # Flush task events first: rules only react to events newer than themselves.
    await ctx.session.flush()
    for r in snap["rules"]:
        await automation.create_rule(ctx, pid, RuleCreate.model_validate(remap(r, ids)))
    for r in snap["recurring"]:
        await automation.create_recurring(ctx, pid, RecurringCreate.model_validate(remap(r, ids)))
    return await projects.get_project(ctx, pid)
