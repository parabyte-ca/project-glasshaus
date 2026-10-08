"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from glasshaus.api import health, ws
from glasshaus.api.errors import install_error_handlers
from glasshaus.api.v1.router import api_router
from glasshaus.config import get_settings
from glasshaus.db import get_engine
from glasshaus.logs import configure_logging, get_logger
from glasshaus.observability import install_metrics, install_tracing
from glasshaus.version import __version__


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log = get_logger(__name__)
    log.info("startup", version=__version__)
    from glasshaus.dbroles import check_least_privilege

    try:
        least_privilege = await check_least_privilege()
    except Exception:  # noqa: BLE001 - database may not be up yet; /readyz reports it
        least_privilege = True
    if not least_privilege:
        log.error(
            "db.role.privileged", hint="connect as a role without SUPERUSER/BYPASSRLS; RLS is not enforced"
        )
        if get_settings().is_production:
            raise RuntimeError("refusing to start: database role bypasses row-level security")
    yield
    await get_engine().dispose()


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Project Glasshaus API",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        description=(
            "REST API for Project Glasshaus. Every capability is also available as an MCP tool. "
            "Authenticate with `Authorization: Bearer <api token>` or the browser session cookies "
            "(unsafe methods then need the `X-CSRF-Token` header). Errors use RFC 9457 problem details."
        ),
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if settings.metrics_enabled:
        install_metrics(app)
    if settings.otel_enabled:
        install_tracing(app)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    app.include_router(ws.router)
    return app


app = create_app()
