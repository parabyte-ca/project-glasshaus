"""MCP tools: organization administration (people, governance settings) and integrations.

Credentials never pass through MCP: SSO client secrets, SCIM tokens, passwords, webhook URLs and
calendar feed URLs are managed in the web app or REST API. Deactivation and deletion preview first.
"""

import uuid
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput
from glasshaus.core.rbac import Scope
from glasshaus.mcp_server.runtime import UNTRUSTED, invoke
from glasshaus.mcp_server.tools_core import DESTRUCTIVE, READ, WRITE, Confirm, ProjectRef, project_id, user_id


def register(server: MCPServer) -> None:
    @server.tool(
        name="manage_users",
        title="Manage people",
        annotations=DESTRUCTIVE,
        description=(
            "Organization admins: list, invite (create without a password; they sign in with SSO or get a "
            "password from an admin), change role/name/capacity, deactivate or reactivate. Deactivating "
            "ends their sessions; it previews unless confirm=true. " + UNTRUSTED
        ),
    )
    async def manage_users(
        action: Literal["list", "create", "update", "deactivate", "reactivate"] = "list",
        user: Annotated[str | None, Field(description="update/deactivate/reactivate: id or email.")] = None,
        email: str | None = None,
        name: str | None = None,
        role: Literal["owner", "admin", "member", "guest"] | None = None,
        capacity_hours_per_day: Annotated[float | None, Field(ge=0, le=24)] = None,
        query: str | None = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        from glasshaus.identity import service as identity
        from glasshaus.identity.schemas import UserCreate, UserUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            if action == "list":
                return {"users": await identity.list_users(ctx, q=query, limit=200)}
            if action == "create":
                if not email or not name:
                    raise InvalidInput("create needs email and name")
                created = await identity.create_user(
                    ctx,
                    UserCreate(email=email, name=name, org_role=role or "member"),
                )
                return {"user": created}
            uid = await user_id(ctx, user)
            if uid is None:
                raise InvalidInput(f"{action} needs user")
            if action in ("deactivate", "reactivate"):
                if action == "deactivate" and not confirm:
                    target = next((u for u in await identity.list_users(ctx, limit=500) if u.id == uid), None)
                    return {"preview": True, "would_deactivate": target, "effect": "their sessions end now"}
                updated = await identity.update_user(ctx, uid, UserUpdate(is_active=action == "reactivate"))
                return {"preview": False, "user": updated}
            changes: dict[str, Any] = {}
            if name:
                changes["name"] = name
            if role:
                changes["org_role"] = role
            if capacity_hours_per_day is not None:
                changes["capacity_minutes"] = int(capacity_hours_per_day * 60)
            return {"user": await identity.update_user(ctx, uid, UserUpdate(**changes))}

        return await invoke(
            "manage_users", Scope.ADMIN, {"action": action, "user": user, "email": email}, run
        )

    @server.tool(name="get_org_settings", title="Get governance settings", annotations=READ)
    async def get_org_settings() -> dict[str, Any]:
        """Retention settings (audit, activity, notifications, deleted tasks) and the AI assistant switch.
        Organization admins."""
        from glasshaus.governance import service as governance

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"settings": await governance.get_settings(ctx)}

        return await invoke("get_org_settings", Scope.ADMIN, {}, run)

    @server.tool(name="update_org_settings", title="Change retention settings", annotations=DESTRUCTIVE)
    async def update_org_settings(
        audit_retention_days: Annotated[int | None, Field(ge=0, le=3650)] = None,
        activity_retention_days: Annotated[int | None, Field(ge=0, le=3650)] = None,
        notification_retention_days: Annotated[int | None, Field(ge=0, le=3650)] = None,
        deleted_task_retention_days: Annotated[int | None, Field(ge=0, le=3650)] = None,
        ai_enabled: Annotated[
            bool | None, Field(description="Turn the in-app AI assistant on or off for the organization.")
        ] = None,
        ai_features: Annotated[
            list[Literal["summaries", "drafting", "risks", "search"]] | None,
            Field(description="AI features people may use when the assistant is on."),
        ] = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        """Retention and AI settings. Shorter retention deletes older data at the next nightly run (0
        keeps forever). Previews unless confirm=true."""
        from glasshaus.governance import service as governance
        from glasshaus.governance.service import OrgSettingsUpdate

        data = OrgSettingsUpdate(
            audit_retention_days=audit_retention_days,
            activity_retention_days=activity_retention_days,
            notification_retention_days=notification_retention_days,
            deleted_task_retention_days=deleted_task_retention_days,
            ai_enabled=ai_enabled,
            ai_features=ai_features,
        )

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            if not confirm:
                current = await governance.get_settings(ctx)
                return {"preview": True, "current": current, "proposed": data.model_dump(exclude_none=True)}
            return {"preview": False, "settings": await governance.update_settings(ctx, data)}

        return await invoke("update_org_settings", Scope.ADMIN, data.model_dump(exclude_none=True), run)

    @server.tool(
        name="manage_integrations",
        title="Manage integrations",
        annotations=DESTRUCTIVE,
        description=(
            "List integrations (Slack, Teams, webhooks, GitHub/GitLab, email-to-task), change their name, "
            "events or enabled state, send a test message, view recent deliveries, or delete one (preview "
            "unless confirm=true). Creating one needs secrets, so use the web app or REST API."
        ),
    )
    async def manage_integrations(
        action: Literal["list", "update", "test", "deliveries", "delete"] = "list",
        integration_id: uuid.UUID | None = None,
        project: ProjectRef | None = None,
        name: str | None = None,
        enabled: bool | None = None,
        events: Annotated[
            list[str] | None, Field(description="Outbound event types, e.g. task.completed.")
        ] = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        from glasshaus.integrations import service as integrations
        from glasshaus.integrations.service import IntegrationUpdate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            if action == "list":
                pid = await project_id(ctx, project) if project else None
                return {
                    "integrations": await integrations.list_integrations(ctx, pid),
                    "event_types": integrations.EVENT_TYPES,
                }
            if integration_id is None:
                raise InvalidInput(f"{action} needs integration_id")
            if action == "update":
                data = IntegrationUpdate(name=name, enabled=enabled, events=events)
                return {"integration": await integrations.update_integration(ctx, integration_id, data)}
            if action == "test":
                return {"delivery": await integrations.test_integration(ctx, integration_id)}
            if action == "deliveries":
                return {"deliveries": await integrations.list_deliveries(ctx, integration_id)}
            if not confirm:
                return {
                    "preview": True,
                    "would_delete": await integrations.get_integration(ctx, integration_id),
                }
            await integrations.delete_integration(ctx, integration_id)
            return {"preview": False, "deleted": str(integration_id)}

        scope = Scope.READ if action in ("list", "deliveries") else Scope.PROJECTS_WRITE
        return await invoke(
            "manage_integrations", scope, {"action": action, "integration_id": str(integration_id)}, run
        )


__all__ = ["WRITE", "register"]
