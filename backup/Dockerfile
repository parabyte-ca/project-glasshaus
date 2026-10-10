# Backup service: PostgreSQL client tools plus age (https://age-encryption.org) to encrypt dumps.
# The scripts themselves are mounted from ./scripts so they update with the checkout.

# age, built from its pinned release with a current Go toolchain (so the binaries carry Go's latest
# security fixes; the module and its dependencies are verified against the Go checksum database).
FROM golang:1.27-alpine AS age
ARG AGE_VERSION=v1.3.2
ENV CGO_ENABLED=0 GOBIN=/out GOFLAGS=-trimpath
RUN go install -ldflags "-s -w -X main.Version=${AGE_VERSION}" \
      "filippo.io/age/cmd/age@${AGE_VERSION}" "filippo.io/age/cmd/age-keygen@${AGE_VERSION}" \
 && /out/age --version

FROM postgres:16-alpine
ARG VERSION=0.0.0
ARG BUILD_SHA=dev
LABEL org.opencontainers.image.title="glasshaus-backup" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${BUILD_SHA}" \
      org.opencontainers.image.source="https://github.com/parabyte-ca/project-glasshaus" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
# Pick up Alpine security fixes released after the base image was built
# (UPGRADE_OS_PACKAGES=false only for networks that block the package mirrors).
ARG UPGRADE_OS_PACKAGES=true
# gosu is only for the postgres server entrypoint, which this image never runs.
RUN if [ "$UPGRADE_OS_PACKAGES" = "true" ]; then apk upgrade --no-cache; fi \
 && rm -f /usr/local/bin/gosu
COPY --from=age /out/age /out/age-keygen /usr/local/bin/
RUN age --version && age-keygen --version
# Compose runs it as GLASSHAUS_BACKUP_UID:GID (the owner of the backup folder); never as root.
USER postgres
