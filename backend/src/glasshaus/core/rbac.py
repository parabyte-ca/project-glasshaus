"""Roles, permissions and token scopes. The single source of truth for authorization.

Effective permissions = role permissions (org -> workspace -> project) ∩ token scopes (if any).
"""

from enum import StrEnum


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class WorkspaceRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectRole(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    COMMENTER = "commenter"
    VIEWER = "viewer"


class Permission(StrEnum):
    ORG_MANAGE = "org.manage"
    USER_MANAGE = "user.manage"
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_CREATE = "workspace.create"
    WORKSPACE_MANAGE = "workspace.manage"
    PROJECT_READ = "project.read"
    PROJECT_CREATE = "project.create"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"
    PROJECT_MANAGE_MEMBERS = "project.manage_members"
    TASK_READ = "task.read"
    TASK_CREATE = "task.create"
    TASK_UPDATE = "task.update"
    TASK_DELETE = "task.delete"
    COMMENT_CREATE = "comment.create"


class Scope(StrEnum):
    """OAuth-style scopes for API tokens (and, from Phase 6, MCP clients)."""

    READ = "read"
    TASKS_WRITE = "tasks:write"
    PROJECTS_WRITE = "projects:write"
    ADMIN = "admin"


_viewer = frozenset({Permission.PROJECT_READ, Permission.TASK_READ})
_commenter = _viewer | {Permission.COMMENT_CREATE}
_editor = _commenter | {Permission.TASK_CREATE, Permission.TASK_UPDATE, Permission.TASK_DELETE}
_admin = _editor | {Permission.PROJECT_UPDATE, Permission.PROJECT_DELETE, Permission.PROJECT_MANAGE_MEMBERS}
_PROJECT_ROLE_PERMS: dict[ProjectRole, frozenset[Permission]] = {
    ProjectRole.VIEWER: _viewer,
    ProjectRole.COMMENTER: frozenset(_commenter),
    ProjectRole.EDITOR: frozenset(_editor),
    ProjectRole.ADMIN: frozenset(_admin),
}

_PROJECT_ROLE_RANK = {
    ProjectRole.VIEWER: 0,
    ProjectRole.COMMENTER: 1,
    ProjectRole.EDITOR: 2,
    ProjectRole.ADMIN: 3,
}

# Workspace role -> implied role on every project in that workspace.
WORKSPACE_TO_PROJECT_ROLE: dict[WorkspaceRole, ProjectRole] = {
    WorkspaceRole.ADMIN: ProjectRole.ADMIN,
    WorkspaceRole.MEMBER: ProjectRole.EDITOR,
    WorkspaceRole.VIEWER: ProjectRole.VIEWER,
}

ORG_ADMIN_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMIN})

# Permission -> scope a token needs to exercise it.
_PERMISSION_SCOPE: dict[Permission, Scope] = {
    Permission.WORKSPACE_READ: Scope.READ,
    Permission.PROJECT_READ: Scope.READ,
    Permission.TASK_READ: Scope.READ,
    Permission.TASK_CREATE: Scope.TASKS_WRITE,
    Permission.TASK_UPDATE: Scope.TASKS_WRITE,
    Permission.TASK_DELETE: Scope.TASKS_WRITE,
    Permission.COMMENT_CREATE: Scope.TASKS_WRITE,
    Permission.PROJECT_CREATE: Scope.PROJECTS_WRITE,
    Permission.PROJECT_UPDATE: Scope.PROJECTS_WRITE,
    Permission.PROJECT_DELETE: Scope.PROJECTS_WRITE,
    Permission.PROJECT_MANAGE_MEMBERS: Scope.PROJECTS_WRITE,
    Permission.WORKSPACE_CREATE: Scope.ADMIN,
    Permission.WORKSPACE_MANAGE: Scope.ADMIN,
    Permission.USER_MANAGE: Scope.ADMIN,
    Permission.ORG_MANAGE: Scope.ADMIN,
}


def project_role_permissions(role: ProjectRole) -> frozenset[Permission]:
    return _PROJECT_ROLE_PERMS[role]


def max_project_role(*roles: ProjectRole | None) -> ProjectRole | None:
    present = [r for r in roles if r is not None]
    return max(present, key=_PROJECT_ROLE_RANK.__getitem__) if present else None


def scope_allows(scopes: frozenset[str] | None, permission: Permission) -> bool:
    """None means an unrestricted principal (interactive session or system)."""
    if scopes is None or Scope.ADMIN in scopes:
        return True
    needed = _PERMISSION_SCOPE[permission]
    if needed == Scope.READ:
        return bool(scopes)  # any scope implies read
    return needed in scopes
