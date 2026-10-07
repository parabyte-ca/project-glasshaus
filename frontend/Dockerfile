# Extra CA certificates (*.crt) for building behind a TLS-inspecting proxy; see backend/Dockerfile.
FROM scratch AS buildca

FROM --platform=$BUILDPLATFORM node:22-alpine AS build
COPY --from=buildca . /tmp/buildca/
RUN cat /tmp/buildca/*.crt > /tmp/extra-ca.pem 2>/dev/null || true
ENV NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem
WORKDIR /src
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
ARG VERSION=0.0.0
ARG BUILD_SHA=dev
LABEL org.opencontainers.image.title="glasshaus-web" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${BUILD_SHA}" \
      org.opencontainers.image.source="https://github.com/parabyte-ca/project-glasshaus" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
ENV GLASSHAUS_API_UPSTREAM=api:8000
USER 101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/nginx-health || exit 1
