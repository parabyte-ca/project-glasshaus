"""Onboarding state lives on the user row (JSON); milestones are read from the person's own work."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, exists, or_, select

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import NotFound, PermissionDenied
from glasshaus.identity.models import User
from glasshaus.onboarding.schemas import Milestones, OnboardingRead, OnboardingUpdate
from glasshaus.projects.models import Project, ProjectMember
from glasshaus.tasks.models import Task

MAX_TIPS = 50


async def _user(ctx: ServiceContext) -> User:
    if ctx.actor.user_id is None:
        raise PermissionDenied("a user principal is required")
    user = await ctx.session.get(User, ctx.actor.user_id)
    if user is None:
        raise NotFound("user not found")
    return user


async def _milestones(ctx: ServiceContext, me: Any, toured: bool) -> Milestones:
    live = Task.deleted_at.is_(None)
    mine = and_(Task.reporter_id == me, live)
    row = (
        await ctx.session.execute(
            select(
                or_(exists().where(mine), exists().where(Project.created_by == me)),
                or_(
                    exists().where(mine, Task.assignee_id.is_not(None), Task.assignee_id != me),
                    exists().where(
                        ProjectMember.project_id == Project.id,
                        Project.created_by == me,
                        ProjectMember.user_id != me,
                    ),
                ),
                exists().where(mine, Task.due_date.is_not(None)),
            )
        )
    ).one()
    return Milestones(
        created_work=bool(row[0]), added_collaborator=bool(row[1]), set_due_date=bool(row[2]), toured=toured
    )


def _read(state: dict[str, Any], milestones: Milestones) -> OnboardingRead:
    finished = state.get("tour_finished_at")
    return OnboardingRead(
        tour=state.get("tour"),
        tour_finished_at=datetime.fromisoformat(finished) if finished else None,
        checklist=state.get("checklist", "open"),
        dismissed_tips=list(state.get("dismissed_tips", [])),
        milestones=milestones,
    )


async def get_onboarding(ctx: ServiceContext) -> OnboardingRead:
    user = await _user(ctx)
    state = dict(user.onboarding or {})
    return _read(state, await _milestones(ctx, user.id, state.get("tour") == "completed"))


async def update_onboarding(ctx: ServiceContext, data: OnboardingUpdate) -> OnboardingRead:
    user = await _user(ctx)
    state: dict[str, Any] = {} if data.reset else dict(user.onboarding or {})
    if data.tour is not None:
        state["tour"] = data.tour
        state["tour_finished_at"] = datetime.now(UTC).isoformat()
    if data.checklist is not None:
        state["checklist"] = data.checklist
    if data.dismiss_tip:
        tips = [t for t in state.get("dismissed_tips", []) if t != data.dismiss_tip]
        state["dismissed_tips"] = [*tips, data.dismiss_tip][-MAX_TIPS:]
    user.onboarding = state  # reassign so SQLAlchemy sees the JSON change
    return _read(state, await _milestones(ctx, user.id, state.get("tour") == "completed"))
