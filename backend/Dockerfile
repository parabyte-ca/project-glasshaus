# One image serves api, worker and mcp (different commands). Multi-arch via buildx.
ARG PYTHON_VERSION=3.12

# Extra CA certificates (*.crt) for building behind a TLS-inspecting proxy. Empty unless overridden with
# a named build context, e.g. compose `additional_contexts: {buildca: /path/to/certs}`. Build stage only.
FROM scratch AS buildca

FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=buildca . /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt PIP_CERT=/etc/ssl/certs/ca-certificates.crt
ARG UV_VERSION=0.11.32
RUN --mount=type=cache,target=/root/.cache/pip pip install "uv==${UV_VERSION}"
ENV UV_SYSTEM_CERTS=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG VERSION=0.0.0
ARG BUILD_SHA=dev
LABEL org.opencontainers.image.title="glasshaus" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${BUILD_SHA}" \
      org.opencontainers.image.source="https://github.com/parabyte-ca/project-glasshaus" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
RUN groupadd --gid 10001 glasshaus \
 && useradd --uid 10001 --gid glasshaus --no-create-home --home-dir /app --shell /usr/sbin/nologin glasshaus
COPY --from=build --chown=root:root /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    GLASSHAUS_BUILD_SHA=${BUILD_SHA}
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "glasshaus.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
