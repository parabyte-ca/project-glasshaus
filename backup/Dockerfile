# Backup service: PostgreSQL client tools plus age (https://age-encryption.org) to encrypt dumps.
# The scripts themselves are mounted from ./scripts so they update with the checkout.

# age: the upstream static release, pinned and checked (bump AGE_VERSION and both checksums together).
FROM postgres:16-alpine AS age
ARG TARGETARCH
ARG AGE_VERSION=v1.3.2
ARG AGE_SHA256_amd64=cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10
ARG AGE_SHA256_arm64=6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4
ADD https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/age-${AGE_VERSION}-linux-${TARGETARCH}.tar.gz /tmp/age.tar.gz
RUN set -eu; \
    case "$TARGETARCH" in amd64) sum="$AGE_SHA256_amd64" ;; arm64) sum="$AGE_SHA256_arm64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; esac; \
    echo "$sum  /tmp/age.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/age.tar.gz -C /tmp

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
COPY --from=age /tmp/age/age /tmp/age/age-keygen /usr/local/bin/
COPY --from=age /tmp/age/LICENSE /usr/local/share/licenses/age/LICENSE
RUN age --version && age-keygen --version
