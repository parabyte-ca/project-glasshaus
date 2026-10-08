"""Portfolios (project groups with health rollups) and OKRs (objectives, key results, check-ins).

Both are organization-wide and visible to everyone except guests. Project data inside them (health,
task-based progress) is shown only for projects the viewer can read. The owner or an organization
admin changes them.
"""

import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select

from glasshaus.core.authz import project_role, require_scope, visible_projects_clause
from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound, PermissionDenied
from glasshaus.core.rbac import OrgRole, Permission
from glasshaus.goals.models import CheckIn, KeyResult, Objective, Portfolio, PortfolioProject
from glasshaus.goals.schemas import (
    CheckInCreate,
    CheckInRead,
    Confidence,
    KeyResultCreate,
    KeyResultKind,
    KeyResultRead,
    KeyResultUpdate,
    ObjectiveCreate,
    ObjectiveRead,
    ObjectiveUpdate,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioRead,
    PortfolioUpdate,
)
from glasshaus.identity.models import User
from glasshaus.projects.models import Project, ProjectStatus, StatusCategory
from glasshaus.tasks.models import Task

HEALTH_ORDER = {"on_track": 0, "at_risk": 1, "off_track": 2}
CONFIDENCE_ORDER = {Confidence.ON_TRACK: 0, Confidence.AT_RISK: 1, Confidence.OFF_TRACK: 2}


def _no_guests(ctx: ServiceContext) -> None:
    if ctx.actor.org_role == OrgRole.GUEST or (ctx.actor.user_id is None and not ctx.actor.is_org_admin):
        raise PermissionDenied("not available to guests")


def _can_edit(ctx: ServiceContext, owner_id: uuid.UUID | None) -> None:
    if not (ctx.actor.is_org_admin or (owner_id is not None and owner_id == ctx.actor.user_id)):
        raise PermissionDenied("only the owner or an organization admin can change this")


async def _visible_project_ids(ctx: ServiceContext, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await ctx.session.scalars(
        select(Project.id).where(Project.id.in_(ids), visible_projects_clause(ctx))
    )
    return set(rows.all())


# --------------------------------------------------------------------------- portfolios


async def _portfolio_projects(ctx: ServiceContext, portfolio_id: uuid.UUID) -> list[Project]:
    rows = await ctx.session.scalars(
        select(Project)
        .join(PortfolioProject, PortfolioProject.project_id == Project.id)
        .where(PortfolioProject.portfolio_id == portfolio_id, visible_projects_clause(ctx))
        .order_by(PortfolioProject.position, Project.key)
    )
    return list(rows.all())


async def list_portfolios(ctx: ServiceContext) -> list[PortfolioRead]:
    _no_guests(ctx)
    portfolios = (await ctx.session.scalars(select(Portfolio).order_by(func.lower(Portfolio.name)))).all()
    counts = dict(
        (
            await ctx.session.execute(
                select(PortfolioProject.portfolio_id, func.count())
                .join(Project, Project.id == PortfolioProject.project_id)
                .where(visible_projects_clause(ctx))
                .group_by(PortfolioProject.portfolio_id)
            )
        ).all()
    )
    return [
        PortfolioRead(
            id=p.id,
            name=p.name,
            description=p.description,
            owner_id=p.owner_id,
            created_at=p.created_at,
            project_count=counts.get(p.id, 0),
        )
        for p in portfolios
    ]


async def _portfolio(ctx: ServiceContext, portfolio_id: uuid.UUID) -> Portfolio:
    _no_guests(ctx)
    portfolio = await ctx.session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise NotFound("portfolio not found")
    return portfolio


async def get_portfolio(ctx: ServiceContext, portfolio_id: uuid.UUID) -> PortfolioDetail:
    from glasshaus.insights.service import project_health

    portfolio = await _portfolio(ctx, portfolio_id)
    projects = [await project_health(ctx, p) for p in await _portfolio_projects(ctx, portfolio_id)]
    total = sum(p.total for p in projects)
    done = sum(p.done for p in projects)
    worst = max((p.health for p in projects), key=HEALTH_ORDER.__getitem__, default="on_track")
    return PortfolioDetail(
        id=portfolio.id,
        name=portfolio.name,
        description=portfolio.description,
        owner_id=portfolio.owner_id,
        created_at=portfolio.created_at,
        project_count=len(projects),
        projects=projects,
        progress=round(done / total, 3) if total else 0.0,
        health=worst,
    )


async def _set_projects(ctx: ServiceContext, portfolio: Portfolio, project_ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(project_ids))
    if missing := set(ids) - await _visible_project_ids(ctx, ids):
        raise NotFound(f"project {sorted(map(str, missing))[0]} not found")
    # Keep projects the editor cannot see: they are not theirs to remove.
    hidden = set(
        (
            await ctx.session.scalars(
                select(PortfolioProject.project_id)
                .join(Project, Project.id == PortfolioProject.project_id)
                .where(PortfolioProject.portfolio_id == portfolio.id, ~visible_projects_clause(ctx))
            )
        ).all()
    )
    await ctx.session.execute(
        delete(PortfolioProject).where(
            PortfolioProject.portfolio_id == portfolio.id, PortfolioProject.project_id.not_in(hidden)
        )
    )
    for position, project_id in enumerate(ids):
        ctx.session.add(
            PortfolioProject(
                tenant_id=ctx.tenant_id,
                portfolio_id=portfolio.id,
                project_id=project_id,
                position=float(position),
            )
        )
    await ctx.session.flush()


async def create_portfolio(ctx: ServiceContext, data: PortfolioCreate) -> PortfolioDetail:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    _no_guests(ctx)
    portfolio = Portfolio(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=data.name,
        description=data.description,
        owner_id=ctx.actor.user_id,
    )
    ctx.session.add(portfolio)
    await ctx.session.flush()
    await _set_projects(ctx, portfolio, data.project_ids)
    return await get_portfolio(ctx, portfolio.id)


async def update_portfolio(
    ctx: ServiceContext, portfolio_id: uuid.UUID, data: PortfolioUpdate
) -> PortfolioDetail:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    portfolio = await _portfolio(ctx, portfolio_id)
    _can_edit(ctx, portfolio.owner_id)
    if data.name is not None:
        portfolio.name = data.name
    if data.description is not None:
        portfolio.description = data.description
    if data.project_ids is not None:
        await _set_projects(ctx, portfolio, data.project_ids)
    await ctx.session.flush()
    return await get_portfolio(ctx, portfolio_id)


async def delete_portfolio(ctx: ServiceContext, portfolio_id: uuid.UUID) -> None:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    portfolio = await _portfolio(ctx, portfolio_id)
    _can_edit(ctx, portfolio.owner_id)
    await ctx.session.delete(portfolio)
    await ctx.session.flush()


# --------------------------------------------------------------------------- OKRs


async def _task_progress(ctx: ServiceContext, kr: KeyResult) -> tuple[int, int] | None:
    """(done, total) of the linked project's live, non-cancelled tasks; None if not visible."""
    if kr.project_id is None:
        return None
    project = await ctx.session.get(Project, kr.project_id)
    if project is None or await project_role(ctx, project) is None:
        return None
    stmt = (
        select(ProjectStatus.category, func.count())
        .select_from(Task)
        .join(ProjectStatus, ProjectStatus.id == Task.status_id)
        .where(
            Task.project_id == kr.project_id,
            Task.deleted_at.is_(None),
            ProjectStatus.category != StatusCategory.CANCELLED,
        )
        .group_by(ProjectStatus.category)
    )
    if kr.tag:
        stmt = stmt.where(Task.tags.contains([kr.tag.strip().lower()]))
    counts = dict((await ctx.session.execute(stmt)).all())
    return counts.get(StatusCategory.DONE, 0), sum(counts.values())


async def _kr_read(ctx: ServiceContext, kr: KeyResult) -> KeyResultRead:
    progress: float | None
    current: float | None = kr.current_value
    total: int | None = None
    if kr.kind == KeyResultKind.TASKS:
        counts = await _task_progress(ctx, kr)
        if counts is None:
            progress = current = None
        else:
            done, total = counts
            current = float(done)
            progress = done / total if total else 0.0
    else:
        span = kr.target_value - kr.start_value
        progress = (kr.current_value - kr.start_value) / span if span else 0.0
    return KeyResultRead(
        id=kr.id,
        objective_id=kr.objective_id,
        title=kr.title,
        kind=kr.kind,
        unit=kr.unit,
        start_value=kr.start_value,
        target_value=kr.target_value,
        current_value=current,
        project_id=kr.project_id,
        tag=kr.tag,
        weight=kr.weight,
        confidence=kr.confidence,
        progress=None if progress is None else round(min(max(progress, 0.0), 1.0), 3),
        total_tasks=total,
    )


async def _objective_read(ctx: ServiceContext, objective: Objective, krs: list[KeyResult]) -> ObjectiveRead:
    reads = [await _kr_read(ctx, kr) for kr in krs]
    weighted = [(r.progress, r.weight) for r in reads if r.progress is not None]
    weight = sum(w for _, w in weighted)
    confidences = [r.confidence for r in reads if r.confidence is not None]
    return ObjectiveRead(
        id=objective.id,
        title=objective.title,
        description=objective.description,
        period=objective.period,
        start_date=objective.start_date,
        end_date=objective.end_date,
        owner_id=objective.owner_id,
        parent_id=objective.parent_id,
        created_at=objective.created_at,
        key_results=reads,
        progress=round(sum(p * w for p, w in weighted) / weight, 3) if weight else None,
        confidence=max(confidences, key=CONFIDENCE_ORDER.__getitem__) if confidences else None,
    )


async def _krs_for(ctx: ServiceContext, objective_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[KeyResult]]:
    out: dict[uuid.UUID, list[KeyResult]] = defaultdict(list)
    if objective_ids:
        rows = await ctx.session.scalars(
            select(KeyResult)
            .where(KeyResult.objective_id.in_(objective_ids))
            .order_by(KeyResult.position, KeyResult.created_at)
        )
        for kr in rows.all():
            out[kr.objective_id].append(kr)
    return out


async def list_objectives(ctx: ServiceContext, *, period: str | None = None) -> list[ObjectiveRead]:
    _no_guests(ctx)
    stmt = select(Objective).order_by(Objective.period.desc(), Objective.created_at)
    if period:
        stmt = stmt.where(Objective.period == period)
    objectives = list((await ctx.session.scalars(stmt)).all())
    krs = await _krs_for(ctx, [o.id for o in objectives])
    return [await _objective_read(ctx, o, krs.get(o.id, [])) for o in objectives]


async def _objective(ctx: ServiceContext, objective_id: uuid.UUID) -> Objective:
    _no_guests(ctx)
    objective = await ctx.session.get(Objective, objective_id)
    if objective is None:
        raise NotFound("objective not found")
    return objective


async def get_objective(ctx: ServiceContext, objective_id: uuid.UUID) -> ObjectiveRead:
    objective = await _objective(ctx, objective_id)
    return await _objective_read(ctx, objective, (await _krs_for(ctx, [objective.id])).get(objective.id, []))


async def _check_parent(
    ctx: ServiceContext, objective_id: uuid.UUID | None, parent_id: uuid.UUID | None
) -> None:
    seen: set[uuid.UUID] = set()
    current = parent_id
    while current is not None:
        if current == objective_id or current in seen:
            raise InvalidInput("an objective cannot support itself (cycle)")
        seen.add(current)
        parent = await ctx.session.get(Objective, current)
        if parent is None:
            raise NotFound("parent objective not found")
        current = parent.parent_id


async def _check_owner(ctx: ServiceContext, owner_id: uuid.UUID | None) -> None:
    if owner_id is not None and await ctx.session.get(User, owner_id) is None:
        raise NotFound("owner not found")


async def _new_kr(
    ctx: ServiceContext, objective_id: uuid.UUID, data: KeyResultCreate, position: float
) -> KeyResult:
    if data.kind == KeyResultKind.TASKS:
        assert data.project_id is not None
        if not await _visible_project_ids(ctx, [data.project_id]):
            raise NotFound("project not found")
    kr = KeyResult(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        objective_id=objective_id,
        title=data.title,
        kind=data.kind,
        unit=data.unit if data.kind == KeyResultKind.METRIC else "",
        start_value=data.start_value,
        target_value=data.target_value,
        current_value=data.start_value if data.current_value is None else data.current_value,
        project_id=data.project_id if data.kind == KeyResultKind.TASKS else None,
        tag=data.tag.strip().lower() if data.tag and data.kind == KeyResultKind.TASKS else None,
        weight=data.weight,
        position=position,
    )
    ctx.session.add(kr)
    return kr


async def create_objective(ctx: ServiceContext, data: ObjectiveCreate) -> ObjectiveRead:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    _no_guests(ctx)
    owner_id = data.owner_id or ctx.actor.user_id
    await _check_owner(ctx, owner_id)
    await _check_parent(ctx, None, data.parent_id)
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise InvalidInput("end_date must be on or after start_date")
    objective = Objective(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        title=data.title,
        description=data.description,
        period=data.period,
        start_date=data.start_date,
        end_date=data.end_date,
        owner_id=owner_id,
        parent_id=data.parent_id,
    )
    ctx.session.add(objective)
    await ctx.session.flush()
    for i, kr in enumerate(data.key_results):
        await _new_kr(ctx, objective.id, kr, float(i))
    await ctx.session.flush()
    return await get_objective(ctx, objective.id)


async def update_objective(
    ctx: ServiceContext, objective_id: uuid.UUID, data: ObjectiveUpdate
) -> ObjectiveRead:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    objective = await _objective(ctx, objective_id)
    _can_edit(ctx, objective.owner_id)
    changes = data.model_dump(exclude_unset=True)
    for field in ("title", "period"):
        if field in changes and changes[field] is None:
            raise InvalidInput(f"{field} cannot be null")
    if "owner_id" in changes:
        await _check_owner(ctx, changes["owner_id"])
    if "parent_id" in changes:
        await _check_parent(ctx, objective.id, changes["parent_id"])
    for field, value in changes.items():
        setattr(objective, field, value)
    if objective.start_date and objective.end_date and objective.end_date < objective.start_date:
        raise InvalidInput("end_date must be on or after start_date")
    await ctx.session.flush()
    return await get_objective(ctx, objective_id)


async def delete_objective(ctx: ServiceContext, objective_id: uuid.UUID) -> None:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    objective = await _objective(ctx, objective_id)
    _can_edit(ctx, objective.owner_id)
    await ctx.session.delete(objective)
    await ctx.session.flush()


async def add_key_result(
    ctx: ServiceContext, objective_id: uuid.UUID, data: KeyResultCreate
) -> KeyResultRead:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    objective = await _objective(ctx, objective_id)
    _can_edit(ctx, objective.owner_id)
    count = await ctx.session.scalar(
        select(func.count()).select_from(KeyResult).where(KeyResult.objective_id == objective_id)
    )
    if (count or 0) >= 10:
        raise InvalidInput("an objective has at most 10 key results")
    kr = await _new_kr(ctx, objective_id, data, float(count or 0))
    await ctx.session.flush()
    return await _kr_read(ctx, kr)


async def _key_result(ctx: ServiceContext, kr_id: uuid.UUID) -> tuple[KeyResult, Objective]:
    _no_guests(ctx)
    kr = await ctx.session.get(KeyResult, kr_id)
    if kr is None:
        raise NotFound("key result not found")
    objective = await ctx.session.get(Objective, kr.objective_id)
    assert objective is not None
    return kr, objective


async def update_key_result(ctx: ServiceContext, kr_id: uuid.UUID, data: KeyResultUpdate) -> KeyResultRead:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    kr, objective = await _key_result(ctx, kr_id)
    _can_edit(ctx, objective.owner_id)
    changes = data.model_dump(exclude_unset=True)
    if "tag" in changes:
        changes["tag"] = changes["tag"].strip().lower() if changes["tag"] else None
    for field in ("title", "unit", "start_value", "target_value", "weight"):
        if field in changes and changes[field] is None:
            raise InvalidInput(f"{field} cannot be null")
    for field, value in changes.items():
        setattr(kr, field, value)
    if kr.kind == KeyResultKind.METRIC and kr.start_value == kr.target_value:
        raise InvalidInput("target_value must differ from start_value")
    await ctx.session.flush()
    return await _kr_read(ctx, kr)


async def delete_key_result(ctx: ServiceContext, kr_id: uuid.UUID) -> None:
    require_scope(ctx, Permission.PROJECT_UPDATE)
    kr, objective = await _key_result(ctx, kr_id)
    _can_edit(ctx, objective.owner_id)
    await ctx.session.delete(kr)
    await ctx.session.flush()


async def check_in(ctx: ServiceContext, kr_id: uuid.UUID, data: CheckInCreate) -> CheckInRead:
    require_scope(ctx, Permission.TASK_UPDATE)
    kr, objective = await _key_result(ctx, kr_id)
    _can_edit(ctx, objective.owner_id)
    if data.value is not None and kr.kind != KeyResultKind.METRIC:
        raise InvalidInput("task-based key results update from their tasks; omit value")
    entry = CheckIn(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        key_result_id=kr.id,
        value=data.value,
        confidence=data.confidence,
        note=data.note,
        author_id=ctx.actor.user_id,
    )
    ctx.session.add(entry)
    if data.value is not None:
        kr.current_value = data.value
    kr.confidence = data.confidence
    await ctx.session.flush()
    return CheckInRead.model_validate(entry)


async def list_check_ins(ctx: ServiceContext, kr_id: uuid.UUID) -> list[CheckInRead]:
    await _key_result(ctx, kr_id)
    rows = await ctx.session.scalars(
        select(CheckIn).where(CheckIn.key_result_id == kr_id).order_by(CheckIn.created_at.desc()).limit(100)
    )
    return [CheckInRead.model_validate(c) for c in rows.all()]
