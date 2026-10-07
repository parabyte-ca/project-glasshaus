"""Authorization checks shared by every service. Invisible resources raise NotFound (no existence leaks);
visible-but-forbidden raise PermissionDenied."""

import uuid

from sqlalchemy import ColumnElement, and_, exists, or_, select, true

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import NotFound, PermissionDenied
from glasshaus.core.rbac import (
    WORKSPACE_TO_PROJECT_ROLE,
    OrgRole,
    Permission,
    ProjectRole,
    WorkspaceRole,
    max_project_role,
    project_role_permissions,
    scope_allows,
)
from glasshaus.identity.models import WorkspaceMember
from glasshaus.projects.models import Project, ProjectMember

ORG_PERMISSIONS: dict[OrgRole, frozenset[Permission]] = {
    OrgRole.OWNER: frozenset(Permission),
    OrgRole.ADMIN: frozenset(Permission),
    OrgRole.MEMBER: frozenset({Permission.WORKSPACE_READ}),
    OrgRole.GUEST: frozenset(),
}


def require_scope(ctx: ServiceContext, permission: Permission) -> None:
    if not scope_allows(ctx.actor.scopes, permission):
        raise PermissionDenied(f"token scope does not allow {permission.value}")


def require_org(ctx: ServiceContext, permission: Permission) -> None:
    require_scope(ctx, permission)
    if permission not in ORG_PERMISSIONS[ctx.actor.org_role]:
        raise PermissionDenied(f"missing permission {permission.value}")


async def workspace_role(ctx: ServiceContext, workspace_id: uuid.UUID) -> WorkspaceRole | None:
    key = ("ws_role", workspace_id)
    if key not in ctx.cache:
        if ctx.actor.is_org_admin:
            ctx.cache[key] = WorkspaceRole.ADMIN
        elif ctx.actor.user_id is None or ctx.actor.org_role == OrgRole.GUEST:
            ctx.cache[key] = None
        else:
            ctx.cache[key] = await ctx.session.scalar(
                select(WorkspaceMember.role).where(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == ctx.actor.user_id
                )
            )
    role: WorkspaceRole | None = ctx.cache[key]
    return role


async def require_workspace(
    ctx: ServiceContext, workspace_id: uuid.UUID, *, manage: bool = False
) -> WorkspaceRole:
    require_scope(ctx, Permission.WORKSPACE_MANAGE if manage else Permission.WORKSPACE_READ)
    role = await workspace_role(ctx, workspace_id)
    if role is None:
        # Guests can still see workspaces that contain a project they belong to.
        if (
            not manage
            and ctx.actor.user_id
            and await ctx.session.scalar(
                select(
                    exists().where(
                        ProjectMember.user_id == ctx.actor.user_id,
                        ProjectMember.project_id == Project.id,
                        Project.workspace_id == workspace_id,
                    )
                )
            )
        ):
            return WorkspaceRole.VIEWER
        raise NotFound("workspace not found")
    if manage and role != WorkspaceRole.ADMIN:
        raise PermissionDenied("workspace admin required")
    return role


async def project_role(ctx: ServiceContext, project: Project) -> ProjectRole | None:
    key = ("project_role", project.id)
    if key not in ctx.cache:
        if ctx.actor.is_org_admin:
            ctx.cache[key] = ProjectRole.ADMIN
        elif ctx.actor.user_id is None:
            ctx.cache[key] = None
        else:
            explicit = await ctx.session.scalar(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == project.id, ProjectMember.user_id == ctx.actor.user_id
                )
            )
            ws_role = await workspace_role(ctx, project.workspace_id)
            implied = WORKSPACE_TO_PROJECT_ROLE[ws_role] if ws_role else None
            ctx.cache[key] = max_project_role(explicit, implied)
    role: ProjectRole | None = ctx.cache[key]
    return role


async def require_project(ctx: ServiceContext, project_id: uuid.UUID, permission: Permission) -> Project:
    project = await ctx.session.get(Project, project_id)
    if project is None:
        raise NotFound("project not found")
    role = await project_role(ctx, project)
    if role is None:
        raise NotFound("project not found")
    require_scope(ctx, permission)
    if permission not in project_role_permissions(role):
        raise PermissionDenied(f"missing permission {permission.value}")
    return project


def visible_projects_clause(ctx: ServiceContext) -> ColumnElement[bool]:
    """SQL predicate on ``Project`` limiting rows to those the actor can read."""
    if ctx.actor.is_org_admin:
        return true()
    uid = ctx.actor.user_id
    explicit = exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == uid)
    if ctx.actor.org_role == OrgRole.GUEST:
        return explicit
    via_workspace = exists().where(
        and_(WorkspaceMember.workspace_id == Project.workspace_id, WorkspaceMember.user_id == uid)
    )
    return or_(explicit, via_workspace)
