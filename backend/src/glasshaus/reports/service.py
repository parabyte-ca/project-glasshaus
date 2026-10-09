"""Saved reports: create, share, run (with optional dashboard filters) and export."""

import csv
import io
import uuid

from sqlalchemy import func, or_, select

from glasshaus.core.authz import require_scope
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.reports import engine
from glasshaus.reports.models import SavedReport
from glasshaus.reports.schemas import (
    ReportDefinition,
    ReportOverrides,
    ReportResult,
    SavedReportCreate,
    SavedReportRead,
    SavedReportUpdate,
)


def _safe(value: str) -> str:
    """Neutralize spreadsheet formulas (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _read(r: SavedReport) -> SavedReportRead:
    return SavedReportRead.model_validate(r)


async def list_reports(ctx: ServiceContext) -> list[SavedReportRead]:
    clause = SavedReport.owner_id == ctx.actor.user_id
    if ctx.actor.org_role != OrgRole.GUEST:
        clause = or_(clause, SavedReport.shared.is_(True))
    rows = await ctx.session.scalars(select(SavedReport).where(clause).order_by(func.lower(SavedReport.name)))
    return [_read(r) for r in rows.all()]


async def _report(ctx: ServiceContext, report_id: uuid.UUID, *, edit: bool) -> SavedReport:
    if edit:
        require_scope(ctx, Permission.TASK_UPDATE)
    r = await ctx.session.get(SavedReport, report_id)
    mine = r is not None and r.owner_id is not None and r.owner_id == ctx.actor.user_id
    visible = r is not None and (mine or (r.shared and ctx.actor.org_role != OrgRole.GUEST))
    if r is None or not visible:
        raise NotFound("report not found")
    if edit and not (mine or ctx.actor.is_org_admin):
        raise PermissionDenied("only the owner or an organization admin can change this report")
    return r


async def get_report(ctx: ServiceContext, report_id: uuid.UUID) -> SavedReportRead:
    return _read(await _report(ctx, report_id, edit=False))


async def create_report(ctx: ServiceContext, data: SavedReportCreate) -> SavedReportRead:
    require_scope(ctx, Permission.TASK_UPDATE)
    if ctx.actor.user_id is None:
        raise PermissionDenied("reports belong to people")
    if data.shared and ctx.actor.org_role == OrgRole.GUEST:
        raise PermissionDenied("guests cannot share reports")
    await engine.run(ctx, data.definition)  # refuse definitions that cannot run (e.g. hidden fields)
    r = SavedReport(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        owner_id=ctx.actor.user_id,
        name=data.name,
        description=data.description,
        shared=data.shared,
        definition=data.definition.model_dump(mode="json"),
    )
    ctx.session.add(r)
    await ctx.session.flush()
    return _read(r)


async def update_report(
    ctx: ServiceContext, report_id: uuid.UUID, data: SavedReportUpdate
) -> SavedReportRead:
    r = await _report(ctx, report_id, edit=True)
    if data.name is not None:
        r.name = data.name
    if data.description is not None:
        r.description = data.description
    if data.shared is not None:
        if data.shared and ctx.actor.org_role == OrgRole.GUEST:
            raise PermissionDenied("guests cannot share reports")
        r.shared = data.shared
    if data.definition is not None:
        await engine.run(ctx, data.definition)
        r.definition = data.definition.model_dump(mode="json")
    await ctx.session.flush()
    return _read(r)


async def delete_report(ctx: ServiceContext, report_id: uuid.UUID) -> None:
    r = await _report(ctx, report_id, edit=True)
    await ctx.session.delete(r)
    await ctx.session.flush()


def _apply(definition: ReportDefinition, overrides: ReportOverrides | None) -> ReportDefinition:
    if overrides is None:
        return definition
    filters = definition.filters.model_copy()
    if overrides.date is not None:
        field = (
            "spent" if definition.source == "time" else (filters.date.field if filters.date else "created")
        )
        filters.date = overrides.date.model_copy(update={"field": field})
    if overrides.project_ids:
        filters.project_ids = overrides.project_ids
    return definition.model_copy(update={"filters": filters})


async def run_definition(ctx: ServiceContext, definition: ReportDefinition) -> ReportResult:
    return await engine.run(ctx, definition)


async def run_report(
    ctx: ServiceContext, report_id: uuid.UUID, overrides: ReportOverrides | None = None
) -> ReportResult:
    r = await _report(ctx, report_id, edit=False)
    return await engine.run(ctx, _apply(ReportDefinition.model_validate(r.definition), overrides))


def to_csv(result: ReportResult) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c.label for c in result.columns])
    for row in result.rows:
        writer.writerow([_safe(label) for label in row.labels] + ["" if v is None else v for v in row.values])
    dims = sum(1 for c in result.columns if c.kind == "dimension")
    if dims:
        writer.writerow(["Total"] + [""] * (dims - 1) + ["" if v is None else v for v in result.totals])
    return out.getvalue()


async def export_report(ctx: ServiceContext, report_id: uuid.UUID) -> tuple[str, str]:
    r = await _report(ctx, report_id, edit=False)
    result = await engine.run(
        ctx, ReportDefinition.model_validate(r.definition).model_copy(update={"limit": 500})
    )
    return r.name, to_csv(result)
