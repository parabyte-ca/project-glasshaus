"""MCP tools: the optional in-app AI assistant (same service calls as /api/v1/ai). Read-only; drafts
and risk flags are proposals to show the user, not changes. They fail with 'unavailable' when the
server has no AI provider or the organization has the assistant turned off."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from glasshaus.core.context import ServiceContext
from glasshaus.core.rbac import Scope
from glasshaus.mcp_server.runtime import UNTRUSTED, invoke
from glasshaus.mcp_server.tools_core import READ, ProjectRef, project_id

# Calls a configured model provider (possibly an external API), so not a closed world.
AI_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def register(server: MCPServer) -> None:
    @server.tool(name="ai_status", title="AI assistant status", annotations=READ)
    async def ai_status() -> dict[str, Any]:
        """Whether the in-app AI assistant is configured and turned on, and which features are allowed."""
        from glasshaus.ai import service as ai

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"status": await ai.get_status(ctx)}

        result: dict[str, Any] = await invoke("ai_status", Scope.READ, {}, run)
        return result

    @server.tool(
        name="ai_status_report",
        title="Write a status update (AI)",
        annotations=AI_READ,
        description=(
            "Have the in-app AI write a status update for a project, returned with the facts it used. "
            "Prefer `status_summary` if you can write the update yourself. " + UNTRUSTED
        ),
    )
    async def ai_status_report(
        project: ProjectRef, days: Annotated[int, Field(ge=1, le=90)] = 7
    ) -> dict[str, Any]:
        from glasshaus.ai import service as ai

        async def run(ctx: ServiceContext) -> Any:
            return await ai.status_report(ctx, await project_id(ctx, project), days=days)

        result: dict[str, Any] = await invoke(
            "ai_status_report", Scope.READ, {"project": project, "days": days}, run
        )
        return result

    @server.tool(
        name="ai_draft_tasks",
        title="Draft tasks from a brief (AI)",
        annotations=AI_READ,
        description=(
            "Have the in-app AI propose tasks for a brief. Nothing is created: show the drafts to the "
            "user and create the ones they accept with `create_task`. " + UNTRUSTED
        ),
    )
    async def ai_draft_tasks(
        project: ProjectRef,
        brief: Annotated[str, Field(min_length=3, max_length=4000)],
        max_tasks: Annotated[int, Field(ge=1, le=15)] = 8,
    ) -> dict[str, Any]:
        from glasshaus.ai import service as ai
        from glasshaus.ai.service import AiDraftRequest

        async def run(ctx: ServiceContext) -> Any:
            data = AiDraftRequest(brief=brief, max_tasks=max_tasks)
            return await ai.draft_tasks(ctx, await project_id(ctx, project), data)

        result: dict[str, Any] = await invoke(
            "ai_draft_tasks", Scope.READ, {"project": project, "max_tasks": max_tasks}, run
        )
        return result

    @server.tool(
        name="ai_flag_risks",
        title="Flag project risks (AI)",
        annotations=AI_READ,
        description="Have the in-app AI list delivery risks with evidence and a next step. " + UNTRUSTED,
    )
    async def ai_flag_risks(project: ProjectRef) -> dict[str, Any]:
        from glasshaus.ai import service as ai

        async def run(ctx: ServiceContext) -> Any:
            return await ai.flag_risks(ctx, await project_id(ctx, project))

        result: dict[str, Any] = await invoke("ai_flag_risks", Scope.READ, {"project": project}, run)
        return result

    @server.tool(
        name="ai_search_tasks",
        title="Search tasks in plain words (AI)",
        annotations=AI_READ,
        description=(
            "Turn a plain-language question ('my overdue tasks in WEB') into task filters with the in-app "
            "AI and run them. Returns the filters and matches. `search_tasks` is cheaper when you can "
            "build the filters yourself. " + UNTRUSTED
        ),
    )
    async def ai_search_tasks(
        query: Annotated[str, Field(min_length=2, max_length=500)],
        project: ProjectRef | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        from glasshaus.ai import service as ai
        from glasshaus.ai.service import AiSearchRequest

        async def run(ctx: ServiceContext) -> Any:
            pid = await project_id(ctx, project) if project else None
            return await ai.search(ctx, AiSearchRequest(query=query, project_id=pid, limit=limit))

        result: dict[str, Any] = await invoke(
            "ai_search_tasks", Scope.READ, {"query": query, "project": project}, run
        )
        return result
