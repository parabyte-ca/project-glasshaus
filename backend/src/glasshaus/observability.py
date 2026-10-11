"""Prometheus metrics and optional OpenTelemetry tracing."""

import hmac
import os
import time
from collections.abc import Awaitable, Callable

# With several API processes (WEB_CONCURRENCY), each keeps its own counters; multiprocess mode
# shares them through files so every scrape sees the whole API. The folder must exist before the
# first metric is created.
if _multiproc := os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    os.makedirs(_multiproc, exist_ok=True)

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

from glasshaus.config import get_settings

REQUESTS = Counter("glasshaus_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "glasshaus_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0),
)


def install_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def _metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        from glasshaus import monitoring

        token = get_settings().metrics_token
        if token is not None and token.get_secret_value():
            given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given.encode(), token.get_secret_value().encode()):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        if _multiproc:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
            body = generate_latest(registry)
        else:
            body = generate_latest()
        return Response(body + (await monitoring.prometheus_text()).encode(), media_type=CONTENT_TYPE_LATEST)


def install_tracing(app: FastAPI) -> None:
    """Enable OTLP tracing. Endpoint and headers come from standard OTEL_* env vars."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": get_settings().otel_service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
