"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from glasshaus.api import health
from glasshaus.config import get_settings
from glasshaus.db import get_engine
from glasshaus.logs import configure_logging, get_logger
from glasshaus.observability import install_metrics, install_tracing
from glasshaus.version import __version__


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_logger(__name__).info("startup", version=__version__)
    yield
    await get_engine().dispose()


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
    app.include_router(health.router)
    return app


app = create_app()
