# syntax=docker/dockerfile:1.24

# -----------------------------------------------------------------------------
# Stage 1: build the wheel.
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv==0.11.15

WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE.txt NOTICE CHANGELOG.md ./
COPY dockerize ./dockerize
RUN uv build --wheel

# -----------------------------------------------------------------------------
# Stage 2: cross-compile syft from source.
#
# Anchore publishes syft release artifacts for linux/{amd64,arm64,ppc64le,
# riscv64,s390x} only — there is no linux/armv7 binary upstream, and the
# `anchore/syft` Docker image has no armv7 manifest either. To keep
# `dockerize --sbom` working on every target arch (including RPi 3 and
# Zero 2 / armv7), we cross-compile syft from source on the build host.
# Running on $BUILDPLATFORM (amd64 on GH runners) skips QEMU emulation —
# Go's native cross-compile produces every target arch in seconds.
# -----------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM golang:1.24-bookworm AS syft-builder
ARG SYFT_VERSION=v1.44.0
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
RUN set -eux; \
    case "$TARGETARCH" in \
      arm) export GOARM="${TARGETVARIANT#v}" ;; \
    esac; \
    GOOS="$TARGETOS" GOARCH="$TARGETARCH" CGO_ENABLED=0 \
      go install -trimpath -ldflags="-s -w" \
        "github.com/anchore/syft/cmd/syft@${SYFT_VERSION}"; \
    mkdir -p /out; \
    find /go/bin -type f -name syft -exec install -m 0755 {} /out/syft \;

# -----------------------------------------------------------------------------
# Stage 3: runtime.
#
# Tools installed from upstream releases rather than Debian apt:
#   - upx           : --compress (Debian's upx-ucl trails upstream + non-free
#                     status varies across mirrors)
#   - docker-buildx : --output-oci (not packaged in bookworm main)
#   - syft          : --sbom (cross-compiled from source in the syft-builder
#                     stage above; anchore doesn't ship linux/armv7 binaries)
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

ARG UPX_VERSION=5.0.2
ARG BUILDX_VERSION=v0.21.2

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      docker.io \
      curl \
      xz-utils \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Architecture-aware install of upx and docker-buildx.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)   upx_arch=amd64_linux;  bx_arch=linux-amd64 ;; \
      aarch64)  upx_arch=arm64_linux;  bx_arch=linux-arm64 ;; \
      armv7l)   upx_arch=armeb_linux;  bx_arch=linux-arm-v7 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/upx/upx/releases/download/v${UPX_VERSION}/upx-${UPX_VERSION}-${upx_arch}.tar.xz" \
      | tar -xJ -C /tmp; \
    install -m 0755 "/tmp/upx-${UPX_VERSION}-${upx_arch}/upx" /usr/local/bin/upx; \
    rm -rf "/tmp/upx-${UPX_VERSION}-${upx_arch}"; \
    mkdir -p /root/.docker/cli-plugins; \
    curl -fsSL -o /root/.docker/cli-plugins/docker-buildx \
      "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.${bx_arch}"; \
    chmod +x /root/.docker/cli-plugins/docker-buildx; \
    upx --version; \
    docker buildx version

# Syft cross-compiled from source in the syft-builder stage above.
COPY --from=syft-builder /out/syft /usr/local/bin/syft
RUN syft version

# Strip the tarball tooling we only needed at install time.
RUN apt-get purge -y curl xz-utils \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

LABEL org.opencontainers.image.source="https://github.com/schubydoo/dockerize2" \
      org.opencontainers.image.title="dockerize2" \
      org.opencontainers.image.description="Pack a dynamically linked ELF binary and its deps into a minimal scratch image." \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.documentation="https://github.com/schubydoo/dockerize2#readme"

WORKDIR /work
ENTRYPOINT ["dockerize"]
CMD ["--help"]
