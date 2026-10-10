"""MCP tools: people, workspaces, projects, tasks, comments, fields, views, activity.

Each tool is a thin adapter over the service layer through ``runtime.invoke`` (scopes, RBAC,
rate limit, audit). Destructive tools preview by default and act only with ``confirm=true``.
"""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput, NotFound
from glasshaus.core.rbac import Scope
from glasshaus.mcp_server.runtime import UNTRUSTED, invoke

ProjectRef = Annotated[str, Field(description="Project key (e.g. WEB) or id.")]
TaskRef = Annotated[str, Field(description="Task reference (e.g. WEB-12) or id.")]
Confirm = Annotated[bool, Field(description="false (default) returns a preview; true performs the change.")]

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


async def project_id(ctx: ServiceContext, ref: str) -> uuid.UUID:
    from glasshaus.projects import service as projects

    try:
        return uuid.UUID(ref)
    except ValueError:
        return (await projects.get_project_by_key(ctx, ref.strip())).id


async def task_id(ctx: ServiceContext, ref: str) -> uuid.UUID:
    from glasshaus.tasks import service as tasks

    return await tasks.resolve_ref(ctx, ref.strip())


async def user_id(ctx: ServiceContext, ref: str | None) -> uuid.UUID | None:
    """'me', a user id, or an email address."""
    from glasshaus.identity import service as identity

    if ref is None or ref == "":
        return None
    if ref == "me":
        if ctx.actor.user_id is None:
            raise InvalidInput("'me' needs a user principal")
        return ctx.actor.user_id
    try:
        return uuid.UUID(ref)
    except ValueError:
        pass
    matches = [u for u in await identity.list_users(ctx, q=ref, limit=5) if u.email.lower() == ref.lower()]
    if not matches:
        raise NotFound(f"no user with email {ref}")
    return matches[0].id


async def status_id(ctx: ServiceContext, project: uuid.UUID, status: str) -> uuid.UUID:
    """A status name, id, or category (todo, in_progress, done, …) in this project."""
    from glasshaus.projects import service as projects

    statuses = await projects.list_statuses(ctx, project)
    wanted = status.strip().lower()
    for s in statuses:
        if str(s.id) == wanted or s.name.lower() == wanted:
            return s.id
    for s in sorted(statuses, key=lambda s: s.position):
        if s.category.value == wanted.replace(" ", "_"):
            return s.id
    names = ", ".join(s.name for s in statuses)
    raise InvalidInput(f"unknown status {status!r}; this project has: {names}")


def register(server: MCPServer) -> None:
    # ------------------------------------------------------------------ people and workspaces

    @server.tool(name="whoami", title="Who am I", annotations=READ)
    async def whoami() -> dict[str, Any]:
        """The signed-in user, organization role, and the scopes this connection may use."""
        from glasshaus.identity import service as identity

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            me = await identity.get_me(ctx)
            return {
                "user": me.model_dump(mode="json"),
                "scopes": sorted(ctx.actor.scopes) if ctx.actor.scopes is not None else ["*"],
                "client": ctx.actor.client,
            }

        return await invoke("whoami", Scope.READ, {}, run)

    @server.tool(name="list_users", title="List people", annotations=READ)
    async def list_users(query: str | None = None, limit: int = 50) -> dict[str, Any]:
        """People in the organization (name/email search). Use ids for assignee fields."""
        from glasshaus.identity import service as identity

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"users": await identity.list_users(ctx, q=query, limit=limit)}

        return await invoke("list_users", Scope.READ, {"query": query}, run)

    @server.tool(name="my_team", title="My team", annotations=READ)
    async def my_team(
        everyone: Annotated[
            bool, Field(description="Include everyone further down, not only direct reports.")
        ] = False,
    ) -> dict[str, Any]:
        """The people who report to you (from the organization's directory) with their open, overdue and
        due-this-week work, time logged this week and last, projects, and work finished this week."""
        from glasshaus.people import service as people

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return (await people.my_team(ctx, everyone=everyone)).model_dump(mode="json")

        return await invoke("my_team", Scope.READ, {"everyone": everyone}, run)

    @server.tool(name="list_workspaces", title="List workspaces", annotations=READ)
    async def list_workspaces() -> dict[str, Any]:
        """Workspaces you can see (projects live in a workspace)."""
        from glasshaus.identity import service as identity

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"workspaces": await identity.list_workspaces(ctx)}

        return await invoke("list_workspaces", Scope.READ, {}, run)

    @server.tool(name="set_workspace_member", title="Set workspace member", annotations=WRITE)
    async def set_workspace_member(
        workspace_id: uuid.UUID,
        user: Annotated[str, Field(description="User id, email or 'me'.")],
        role: Annotated[
            Literal["admin", "member", "viewer"] | None, Field(description="null removes them.")
        ] = None,
    ) -> dict[str, Any]:
        """Add, change or remove someone's workspace role (workspace admins)."""
        from glasshaus.identity import service as identity
        from glasshaus.identity.schemas import WorkspaceMemberSet

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            uid = await user_id(ctx, user)
            assert uid is not None
            if role is None:
                await identity.remove_workspace_member(ctx, workspace_id, uid)
                return {"removed": str(uid)}
            member = await identity.set_workspace_member(
                ctx, workspace_id, WorkspaceMemberSet(user_id=uid, role=role)
            )
            return {"member": member}

        return await invoke(
            "set_workspace_member",
            Scope.ADMIN,
            {"workspace_id": str(workspace_id), "user": user, "role": role},
            run,
        )

    # ------------------------------------------------------------------ projects

    @server.tool(name="search_projects", title="Search projects", annotations=READ)
    async def search_projects(
        query: str | None = None, workspace_id: uuid.UUID | None = None, include_archived: bool = False
    ) -> dict[str, Any]:
        """Projects you can see, optionally filtered by name/key text or workspace."""
        from glasshaus.projects import service as projects

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            found = await projects.list_projects(
                ctx, workspace_id=workspace_id, include_archived=include_archived, q=query
            )
            return {"projects": found}

        return await invoke("search_projects", Scope.READ, {"query": query}, run)

    @server.tool(
        name="get_project",
        title="Get project",
        annotations=READ,
        description="A project with its statuses, members, custom fields and saved views. " + UNTRUSTED,
    )
    async def get_project(project: ProjectRef) -> dict[str, Any]:
        from glasshaus.fields import service as fields
        from glasshaus.projects import service as projects
        from glasshaus.views import service as views

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            return {
                "project": await projects.get_project(ctx, pid),
                "members": await projects.list_project_members(ctx, pid),
                "custom_fields": await fields.list_fields(ctx, pid),
                "views": await views.list_views(ctx, pid),
            }

        return await invoke("get_project", Scope.READ, {"project": project}, run, target=project)

    @server.tool(name="create_project", title="Create project", annotations=WRITE)
    async def create_project(
        workspace_id: uuid.UUID,
        key: Annotated[
            str, Field(description="2-10 uppercase letters/digits, starting with a letter, e.g. WEB.")
        ],
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a project (you become its admin). It starts with default statuses."""
        from glasshaus.projects import service as projects
        from glasshaus.projects.schemas import ProjectCreate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            data = ProjectCreate(
                workspace_id=workspace_id, key=key.upper(), name=name, description=description
            )
            return {"project": await projects.create_project(ctx, data)}

        return await invoke(
            "create_project", Scope.PROJECTS_WRITE, {"key": key, "name": name}, run, target=key
        )

    @server.tool(name="update_project", title="Update project", annotations=WRITE)
    async def update_project(
        project: ProjectRef,
        name: str | None = None,
        description: str | None = None,
        archived: bool | None = None,
        auto_schedule: Annotated[
            bool | None, Field(description="Move dependent tasks later automatically.")
        ] = None,
    ) -> dict[str, Any]:
        """Rename, describe, archive/unarchive a project or toggle auto-scheduling."""
        from glasshaus.projects import service as projects
        from glasshaus.projects.schemas import ProjectUpdate

        patch = {
            k: v
            for k, v in {
                "name": name,
                "description": description,
                "archived": archived,
                "auto_schedule": auto_schedule,
            }.items()
            if v is not None
        }

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            return {"project": await projects.update_project(ctx, pid, ProjectUpdate.model_validate(patch))}

        return await invoke(
            "update_project", Scope.PROJECTS_WRITE, {"project": project, **patch}, run, target=project
        )

    @server.tool(name="delete_project", title="Delete project", annotations=DESTRUCTIVE)
    async def delete_project(project: ProjectRef, confirm: Confirm = False) -> dict[str, Any]:
        """Permanently delete a project and all its tasks. Without confirm=true, only previews."""
        from glasshaus.projects import service as projects

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            preview = await projects.delete_project(ctx, pid, dry_run=not confirm)
            return {"preview": not confirm, "result": preview}

        return await invoke(
            "delete_project",
            Scope.PROJECTS_WRITE,
            {"project": project, "confirm": confirm},
            run,
            target=project,
        )

    @server.tool(name="set_project_member", title="Set project member", annotations=WRITE)
    async def set_project_member(
        project: ProjectRef,
        user: Annotated[str, Field(description="User id, email or 'me'.")],
        role: Annotated[
            Literal["admin", "editor", "commenter", "viewer"] | None, Field(description="null removes them.")
        ] = None,
    ) -> dict[str, Any]:
        """Grant, change or remove someone's role on a project (project admins)."""
        from glasshaus.projects import service as projects
        from glasshaus.projects.schemas import ProjectMemberSet

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid, uid = await project_id(ctx, project), await user_id(ctx, user)
            assert uid is not None
            if role is None:
                await projects.remove_project_member(ctx, pid, uid)
                return {"removed": str(uid)}
            return {
                "member": await projects.set_project_member(
                    ctx, pid, ProjectMemberSet(user_id=uid, role=role)
                )
            }

        return await invoke(
            "set_project_member", Scope.PROJECTS_WRITE, {"project": project, "user": user, "role": role}, run
        )

    @server.tool(name="manage_statuses", title="Manage workflow statuses", annotations=WRITE)
    async def manage_statuses(
        project: ProjectRef,
        action: Literal["list", "create", "update", "delete"] = "list",
        status: Annotated[
            str | None, Field(description="Existing status name or id (update/delete).")
        ] = None,
        name: str | None = None,
        category: Literal["backlog", "todo", "in_progress", "done", "cancelled"] | None = None,
        color: Annotated[str | None, Field(description="#rrggbb")] = None,
        replacement: Annotated[
            str | None, Field(description="delete: move its tasks to this status.")
        ] = None,
    ) -> dict[str, Any]:
        """List or change a project's workflow statuses."""
        from glasshaus.projects import service as projects
        from glasshaus.projects.schemas import StatusCreate, StatusUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            if action == "create":
                if not name or not category:
                    raise InvalidInput("create needs name and category")
                body = {"name": name, "category": category, **({"color": color} if color else {})}
                await projects.create_status(ctx, pid, StatusCreate.model_validate(body))
            elif action in ("update", "delete"):
                if not status:
                    raise InvalidInput(f"{action} needs status")
                sid = await status_id(ctx, pid, status)
                if action == "update":
                    patch = {
                        k: v for k, v in {"name": name, "category": category, "color": color}.items() if v
                    }
                    await projects.update_status(ctx, pid, sid, StatusUpdate.model_validate(patch))
                else:
                    rid = await status_id(ctx, pid, replacement) if replacement else None
                    await projects.delete_status(ctx, pid, sid, replacement_id=rid)
            return {"statuses": await projects.list_statuses(ctx, pid)}

        scope = Scope.READ if action == "list" else Scope.PROJECTS_WRITE
        return await invoke(
            "manage_statuses", scope, {"project": project, "action": action, "name": name}, run
        )

    # ------------------------------------------------------------------ tasks

    @server.tool(
        name="search_tasks",
        title="Search tasks",
        annotations=READ,
        description="Find tasks with filters. Returns a page and next_cursor. " + UNTRUSTED,
    )
    async def search_tasks(
        project: ProjectRef | None = None,
        query: Annotated[str | None, Field(description="Text in the key or title.")] = None,
        status_categories: list[Literal["backlog", "todo", "in_progress", "done", "cancelled"]] | None = None,
        assignee: Annotated[str | None, Field(description="'me', a user id or email.")] = None,
        unassigned: bool | None = None,
        priorities: list[Literal["none", "low", "medium", "high", "urgent"]] | None = None,
        tags: Annotated[list[str] | None, Field(description="Tasks having all of these tags.")] = None,
        due_before: date | None = None,
        due_after: date | None = None,
        top_level_only: bool = False,
        sort: Literal[
            "position", "created_at", "updated_at", "due_date", "priority", "number", "title"
        ] = "position",
        descending: bool = False,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        from glasshaus.tasks import service as tasks
        from glasshaus.tasks.schemas import TaskQuery

        async def run(ctx: ServiceContext) -> Any:
            uid = await user_id(ctx, assignee)
            q = TaskQuery.model_validate(
                {
                    "project_id": await project_id(ctx, project) if project else None,
                    "q": query,
                    "status_categories": status_categories,
                    "assignee_ids": [uid] if uid else None,
                    "unassigned": unassigned,
                    "priorities": priorities,
                    "tags": tags,
                    "due_before": due_before,
                    "due_after": due_after,
                    "top_level_only": top_level_only,
                    "sort": sort,
                    "descending": descending,
                    "limit": limit,
                    "cursor": cursor,
                }
            )
            return await tasks.list_tasks(ctx, q)

        return await invoke("search_tasks", Scope.READ, {"project": project, "query": query}, run)

    @server.tool(
        name="get_task",
        title="Get task",
        annotations=READ,
        description="A task with your permissions on it, dependencies and (optionally) comments. "
        + UNTRUSTED,
    )
    async def get_task(task: TaskRef, include_comments: bool = True) -> dict[str, Any]:
        from glasshaus.collab import service as collab
        from glasshaus.scheduling import service as scheduling
        from glasshaus.tasks import service as tasks

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            tid = await task_id(ctx, task)
            out: dict[str, Any] = {
                "task": await tasks.get_task(ctx, tid),
                "permissions": await tasks.can(ctx, tid),
                "dependencies": await scheduling.task_dependencies(ctx, str(tid)),
            }
            if include_comments:
                out["comments"] = await collab.list_comments(ctx, tid)
            return out

        return await invoke("get_task", Scope.READ, {"task": task}, run, target=task)

    @server.tool(name="create_task", title="Create task", annotations=WRITE)
    async def create_task(
        project: ProjectRef,
        title: str,
        description: Annotated[str, Field(description="Markdown.")] = "",
        status: Annotated[
            str | None, Field(description="Status name or category; default the first to-do.")
        ] = None,
        priority: Literal["none", "low", "medium", "high", "urgent"] = "none",
        assignee: Annotated[str | None, Field(description="'me', a user id or email.")] = None,
        parent: Annotated[str | None, Field(description="Parent task reference, for a subtask.")] = None,
        start_date: date | None = None,
        due_date: date | None = None,
        estimate_minutes: int | None = None,
        tags: list[str] | None = None,
        custom_fields: Annotated[dict[str, Any] | None, Field(description="Field id -> value.")] = None,
    ) -> dict[str, Any]:
        """Create a task and return it with its reference (e.g. WEB-42)."""
        from glasshaus.tasks import service as tasks
        from glasshaus.tasks.schemas import TaskCreate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            data = TaskCreate(
                project_id=pid,
                title=title,
                description=description,
                status_id=await status_id(ctx, pid, status) if status else None,
                priority=priority,
                assignee_id=await user_id(ctx, assignee),
                parent_id=await task_id(ctx, parent) if parent else None,
                start_date=start_date,
                due_date=due_date,
                estimate_minutes=estimate_minutes,
                tags=tags or [],
                custom_fields=custom_fields or {},
            )
            return {"task": await tasks.create_task(ctx, data)}

        return await invoke(
            "create_task", Scope.TASKS_WRITE, {"project": project, "title": title}, run, target=project
        )

    @server.tool(name="update_task", title="Update task", annotations=WRITE)
    async def update_task(
        task: TaskRef,
        title: str | None = None,
        description: str | None = None,
        priority: Literal["none", "low", "medium", "high", "urgent"] | None = None,
        assignee: Annotated[str | None, Field(description="'me', id or email; 'none' to unassign.")] = None,
        start_date: date | None = None,
        due_date: date | None = None,
        clear_dates: bool = False,
        estimate_minutes: int | None = None,
        tags: list[str] | None = None,
        custom_fields: dict[str, Any] | None = None,
        expected_version: Annotated[
            int | None, Field(description="Fail if someone changed it meanwhile.")
        ] = None,
    ) -> dict[str, Any]:
        """Change task fields (only those given). Use change_status to move it through the workflow."""
        from glasshaus.tasks import service as tasks
        from glasshaus.tasks.schemas import TaskUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            tid = await task_id(ctx, task)
            patch: dict[str, Any] = {
                k: v
                for k, v in {
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "start_date": start_date,
                    "due_date": due_date,
                    "estimate_minutes": estimate_minutes,
                    "tags": tags,
                    "custom_fields": custom_fields,
                    "expected_version": expected_version,
                }.items()
                if v is not None
            }
            if assignee is not None:
                patch["assignee_id"] = None if assignee == "none" else await user_id(ctx, assignee)
            if clear_dates:
                patch.update(start_date=None, due_date=None)
            return {"task": await tasks.update_task(ctx, tid, TaskUpdate.model_validate(patch))}

        return await invoke("update_task", Scope.TASKS_WRITE, {"task": task}, run, target=task)

    @server.tool(name="change_status", title="Change task status", annotations=WRITE)
    async def change_status(
        task: TaskRef,
        status: Annotated[
            str, Field(description="Status name (e.g. 'In progress') or category (e.g. done).")
        ],
    ) -> dict[str, Any]:
        """Move a task to another workflow status."""
        from glasshaus.tasks import service as tasks
        from glasshaus.tasks.schemas import TaskUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            tid = await task_id(ctx, task)
            current = await tasks.get_task(ctx, tid)
            sid = await status_id(ctx, current.project_id, status)
            return {"task": await tasks.update_task(ctx, tid, TaskUpdate(status_id=sid))}

        return await invoke(
            "change_status", Scope.TASKS_WRITE, {"task": task, "status": status}, run, target=task
        )

    @server.tool(name="bulk_update_tasks", title="Bulk update tasks", annotations=WRITE)
    async def bulk_update_tasks(
        task_refs: Annotated[list[str], Field(description="Task references or ids (max 500).")],
        status_category: Literal["backlog", "todo", "in_progress", "done", "cancelled"] | None = None,
        priority: Literal["none", "low", "medium", "high", "urgent"] | None = None,
        assignee: Annotated[str | None, Field(description="'me', id or email.")] = None,
        due_date: date | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        """Apply one change to many tasks. Without confirm=true, returns which tasks would change."""
        from glasshaus.tasks import service as tasks
        from glasshaus.tasks.schemas import TaskBulkPatch, TaskBulkUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            ids = [await task_id(ctx, t) for t in task_refs]
            if not confirm:
                found = [await tasks.get_task(ctx, i) for i in ids]
                return {"preview": True, "tasks": [{"key": t.key, "title": t.title} for t in found]}
            patch = TaskBulkPatch(
                status_category=status_category,
                priority=priority,
                assignee_id=await user_id(ctx, assignee),
                due_date=due_date,
                add_tags=add_tags or [],
                remove_tags=remove_tags or [],
            )
            return {
                "preview": False,
                "result": await tasks.bulk_update(ctx, TaskBulkUpdate(task_ids=ids, patch=patch)),
            }

        return await invoke(
            "bulk_update_tasks", Scope.TASKS_WRITE, {"tasks": task_refs, "confirm": confirm}, run
        )

    @server.tool(name="delete_tasks", title="Delete tasks", annotations=DESTRUCTIVE)
    async def delete_tasks(
        task_refs: Annotated[list[str], Field(description="Task references or ids.")],
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        """Delete tasks and their subtasks (restorable with restore_task). Without confirm=true, previews."""
        from glasshaus.tasks import service as tasks

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            ids = [await task_id(ctx, t) for t in task_refs]
            return {"preview": not confirm, "result": await tasks.delete_tasks(ctx, ids, dry_run=not confirm)}

        return await invoke("delete_tasks", Scope.TASKS_WRITE, {"tasks": task_refs, "confirm": confirm}, run)

    @server.tool(name="restore_task", title="Restore task", annotations=WRITE)
    async def restore_task(task: TaskRef) -> dict[str, Any]:
        """Undo a task deletion."""
        from glasshaus.tasks import service as tasks

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"task": await tasks.restore_task(ctx, await task_id(ctx, task))}

        return await invoke("restore_task", Scope.TASKS_WRITE, {"task": task}, run, target=task)

    # ------------------------------------------------------------------ fields, comments, views, activity

    @server.tool(name="manage_custom_fields", title="Manage custom fields", annotations=WRITE)
    async def manage_custom_fields(
        project: ProjectRef,
        action: Literal["list", "create", "update", "delete"] = "list",
        field_id: uuid.UUID | None = None,
        name: str | None = None,
        type: Literal[  # noqa: A002 - matches the REST field name
            "text", "number", "date", "select", "multi_select", "user", "checkbox", "url"
        ]
        | None = None,
        options: Annotated[list[str] | None, Field(description="select types: option labels.")] = None,
        required: bool | None = None,
        confirm: Annotated[
            bool, Field(description="delete: true to delete the field and its values.")
        ] = False,
    ) -> dict[str, Any]:
        """List or change a project's custom fields. Deleting needs confirm=true."""
        from glasshaus.fields import service as fields
        from glasshaus.fields.schemas import FieldCreate, FieldUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            opts = [{"label": o} for o in options] if options else None
            if action == "create":
                if not name or not type:
                    raise InvalidInput("create needs name and type")
                body: dict[str, Any] = {"name": name, "type": type, "required": bool(required)}
                if opts:
                    body["options"] = opts
                await fields.create_field(ctx, pid, FieldCreate.model_validate(body))
            elif action == "update":
                if field_id is None:
                    raise InvalidInput("update needs field_id")
                patch = {
                    k: v
                    for k, v in {"name": name, "required": required, "options": opts}.items()
                    if v is not None
                }
                await fields.update_field(ctx, pid, field_id, FieldUpdate.model_validate(patch))
            elif action == "delete":
                if field_id is None:
                    raise InvalidInput("delete needs field_id")
                if not confirm:
                    return {
                        "preview": True,
                        "message": "Deleting removes the field and its values on every task.",
                    }
                await fields.delete_field(ctx, pid, field_id)
            return {"fields": await fields.list_fields(ctx, pid)}

        scope = Scope.READ if action == "list" else Scope.PROJECTS_WRITE
        return await invoke("manage_custom_fields", scope, {"project": project, "action": action}, run)

    @server.tool(name="post_comment", title="Post comment", annotations=WRITE)
    async def post_comment(
        task: TaskRef,
        body: Annotated[str, Field(description="Markdown. Mention with @email or @[Name](user:<id>).")],
    ) -> dict[str, Any]:
        """Comment on a task (mentioned people are notified)."""
        from glasshaus.collab import service as collab
        from glasshaus.collab.schemas import CommentCreate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {
                "comment": await collab.create_comment(
                    ctx, await task_id(ctx, task), CommentCreate(body=body)
                )
            }

        return await invoke("post_comment", Scope.TASKS_WRITE, {"task": task}, run, target=task)

    @server.tool(
        name="list_comments",
        title="List comments",
        annotations=READ,
        description="A task's comments, oldest first. " + UNTRUSTED,
    )
    async def list_comments(task: TaskRef) -> dict[str, Any]:
        from glasshaus.collab import service as collab

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"comments": await collab.list_comments(ctx, await task_id(ctx, task))}

        return await invoke("list_comments", Scope.READ, {"task": task}, run, target=task)

    @server.tool(name="list_notifications", title="List notifications", annotations=READ)
    async def list_notifications(unread_only: bool = True, limit: int = 30) -> dict[str, Any]:
        """Your notifications (mentions, assignments, comments, automations)."""
        from glasshaus.collab import service as collab

        async def run(ctx: ServiceContext) -> Any:
            return await collab.list_notifications(ctx, unread_only=unread_only, limit=limit)

        return await invoke("list_notifications", Scope.READ, {}, run)

    @server.tool(name="get_activity", title="Get activity", annotations=READ)
    async def get_activity(
        task: TaskRef | None = None, project: ProjectRef | None = None, limit: int = 30
    ) -> dict[str, Any]:
        """Recent changes (who did what), newest first, for a task, a project, or everything you see."""
        from glasshaus.collab import service as collab

        async def run(ctx: ServiceContext) -> Any:
            return await collab.activity(
                ctx,
                task_id=await task_id(ctx, task) if task else None,
                project_id=await project_id(ctx, project) if project else None,
                limit=limit,
            )

        return await invoke("get_activity", Scope.READ, {"task": task, "project": project}, run)

    @server.tool(name="get_audit_log", title="Get audit log", annotations=READ)
    async def get_audit_log(
        action: Annotated[str | None, Field(description="Action prefix, e.g. mcp.delete_tasks.")] = None,
        user: Annotated[str | None, Field(description="'me', a user id or an email.")] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        """Audited actions (every MCP tool call with user, client and outcome). Organization admins."""
        from glasshaus.audit import service as audit

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            uid = await user_id(ctx, user)
            return {"entries": await audit.list_entries(ctx, action=action, actor_id=uid, limit=limit)}

        return await invoke("get_audit_log", Scope.ADMIN, {"action": action, "user": user}, run)

    @server.tool(name="list_views", title="List saved views", annotations=READ)
    async def list_views(project: ProjectRef) -> dict[str, Any]:
        """Saved views in a project (shared ones and yours)."""
        from glasshaus.views import service as views

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"views": await views.list_views(ctx, await project_id(ctx, project))}

        return await invoke("list_views", Scope.READ, {"project": project}, run)

    @server.tool(
        name="run_view",
        title="Run saved view",
        annotations=READ,
        description="The tasks a saved view selects, in its sort order. " + UNTRUSTED,
    )
    async def run_view(view_id: uuid.UUID, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        from glasshaus.views import service as views

        async def run(ctx: ServiceContext) -> Any:
            return await views.run_view(ctx, view_id, limit=limit, cursor=cursor)

        return await invoke("run_view", Scope.READ, {"view_id": str(view_id)}, run)
