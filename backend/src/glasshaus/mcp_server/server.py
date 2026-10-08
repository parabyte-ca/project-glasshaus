"""MCP server (official Python SDK): tools, resources and prompts over the service layer, with
OAuth 2.1 (PKCE, dynamic client registration) and personal API tokens.

OAuth needs an HTTPS issuer (or localhost). On plain HTTP off localhost the server accepts API
tokens only; put it behind an HTTPS reverse proxy and set GLASSHAUS_MCP_PUBLIC_URL to enable OAuth.
"""

from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

import glasshaus.models  # noqa: F401 - register every table so foreign keys resolve in this process
from glasshaus.config import get_settings
from glasshaus.mcp_server import resources, tools_core, tools_plan
from glasshaus.mcp_server.auth import GlasshausOAuthProvider, GlasshausTokenVerifier
from glasshaus.mcp_server.runtime import UNTRUSTED
from glasshaus.oauth.service import ALL_SCOPES
from glasshaus.version import BUILD_SHA, __version__

INSTRUCTIONS = (
    "Project Glasshaus: projects, tasks, dependencies, time, automations, reports and goals. Refer to "
    "projects by key (WEB) and tasks by reference (WEB-12). Destructive tools return a preview unless "
    "called with confirm=true; show the preview to the user and confirm before repeating the call. "
    "Use `status_summary` for status reports. " + UNTRUSTED
)


def oauth_enabled(public_url: str) -> bool:
    parts = urlsplit(public_url)
    return parts.scheme == "https" or parts.hostname in {"localhost", "127.0.0.1"}


def build_server() -> MCPServer:
    settings = get_settings()
    public = settings.mcp_public_url.rstrip("/")
    auth_kwargs: dict[str, object]
    if oauth_enabled(public):
        auth_kwargs = {
            "auth_server_provider": GlasshausOAuthProvider(),
            "auth": AuthSettings(
                issuer_url=public,
                resource_server_url=f"{public}/mcp",
                service_documentation_url=f"{settings.public_url.rstrip('/')}/docs",
                # Registration permits every scope; the user grants a subset on the consent page.
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=ALL_SCOPES, default_scopes=ALL_SCOPES
                ),
                revocation_options=RevocationOptions(enabled=True),
                required_scopes=[],
                validate_token_resource=False,  # audience checked in auth.resolve_bearer
            ),
        }
    else:
        auth_kwargs = {
            "token_verifier": GlasshausTokenVerifier(),
            "auth": AuthSettings(
                issuer_url=public,
                resource_server_url=f"{public}/mcp",
                required_scopes=[],
                validate_token_resource=False,  # audience checked in auth.resolve_bearer
            ),
        }
    server: MCPServer = MCPServer(
        name="glasshaus",
        title="Project Glasshaus",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url=settings.public_url,
        **auth_kwargs,  # type: ignore[arg-type]
    )

    @server.tool(name="server_info", title="Server information")
    def server_info() -> dict[str, str]:
        """Return the Glasshaus server name, version and build."""
        return {"name": "Project Glasshaus", "version": __version__, "build": BUILD_SHA}

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)  # type: ignore[untyped-decorator]
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    tools_core.register(server)
    tools_plan.register(server)
    resources.register(server)
    return server


server = build_server()


def create_http_app() -> Starlette:
    settings = get_settings()
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=[settings.public_url],
        ),
        host="0.0.0.0",  # noqa: S104 - bound inside the container; host exposure is set in compose
    )
