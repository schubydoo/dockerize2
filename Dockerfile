# syntax=docker/dockerfile:1.24

# -----------------------------------------------------------------------------
# Stage 1: pull uv via a $BUILDPLATFORM-scoped alias.
#
# Bare `COPY --from=ghcr.io/astral-sh/uv:0.11.15@sha256:...` makes BuildKit
# resolve the source image's manifest for *every* target platform of the
# final build (amd64, arm64, arm/v7) — but the uv image has no arm/v7
# manifest, so the resolve step 404s and the whole build fails. Wrapping
# the image in a named stage explicitly pinned to $BUILDPLATFORM tells
# BuildKit "only ever resolve this source for the build host", which it
# does once.
# -----------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d AS uv-source

# -----------------------------------------------------------------------------
# Stage 2: build the wheel.
#
# Runs on $BUILDPLATFORM (always amd64 on GH runners). dockerize2 is pure
# Python so `uv build --wheel` produces a single `py3-none-any` wheel that
# every per-arch runtime stage can install — no point QEMU-emulating the
# build on arm64/armv7.
# -----------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM python:3.14-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=uv-source /uv /usr/local/bin/uv

WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE.txt NOTICE CHANGELOG.md ./
COPY dockerize ./dockerize
RUN uv build --wheel

# -----------------------------------------------------------------------------
# Stage 3: cross-compile syft from source.
#
# Anchore publishes syft release artifacts for linux/{amd64,arm64,ppc64le,
# riscv64,s390x} only — there is no linux/armv7 binary upstream, and the
# `anchore/syft` Docker image has no armv7 manifest either. To keep
# `dockerize --sbom` working on every target arch (including RPi 3 and
# Zero 2 / armv7), we cross-compile syft from source on the build host.
# Running on $BUILDPLATFORM (amd64 on GH runners) skips QEMU emulation —
# Go's native cross-compile produces every target arch in seconds.
# -----------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM golang:1.26-bookworm@sha256:386d475a660466863d9f8c766fec64d7fdad3edac2c6a05020c09534d71edb4b AS syft-builder
ARG SYFT_VERSION=v1.44.0
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
RUN set -eux; \
    case "$TARGETARCH" in \
      arm) export GOARM="${TARGETVARIANT#v}" ;; \
    esac; \
    GOOS="$TARGETOS" GOARCH="$TARGETARCH" CGO_ENABLED=0 \
      go install -trimpath -ldflags="-s -w -X main.version=${SYFT_VERSION}" \
        "github.com/anchore/syft/cmd/syft@${SYFT_VERSION}"; \
    mkdir -p /out; \
    find /go/bin -type f -name syft -exec install -m 0755 {} /out/syft \;

# -----------------------------------------------------------------------------
# Stage 4: runtime.
#
# Tools installed from upstream releases rather than Debian apt:
#   - docker (CLI)  : --runtime docker. We install ONLY the static client from
#                     download.docker.com, not the `docker.io` apt package.
#                     dockerize talks to the *host's* daemon over the mounted
#                     socket, so the in-container dockerd/containerd/runc that
#                     `docker.io` bundles are never run — ~170 MB of dead
#                     weight. The static client is also far newer than
#                     bookworm's docker.io (20.10.x).
#   - upx           : --compress (Debian's upx-ucl trails upstream + non-free
#                     status varies across mirrors)
#   - docker-buildx : --output-oci (not packaged in bookworm main)
#   - syft          : --sbom (cross-compiled from source in the syft-builder
#                     stage above; anchore doesn't ship linux/armv7 binaries)
# -----------------------------------------------------------------------------
FROM python:3.14-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

ARG UPX_VERSION=5.1.1
ARG BUILDX_VERSION=v0.34.1
ARG DOCKER_VERSION=29.5.2

# The pinned base image lags Debian's security archive: it ships libgnutls30
# 3.7.9-2+deb12u6 while deb12u7 (fixing the GnuTLS CVE batch — CVE-2026-33845,
# CVE-2026-42010, and others) is already published. Pull the patched package on
# top of the pinned base. `--only-upgrade` (no exact version pin) always moves
# forward, so it becomes a harmless no-op once the base image itself catches up
# — unlike a pinned `=deb12u7`, which would fail the build by implying a
# downgrade. Drop this once the base no longer lags.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      curl \
      xz-utils \
      ca-certificates \
 && apt-get install --no-install-recommends -y --only-upgrade libgnutls30 \
 && rm -rf /var/lib/apt/lists/*

# Architecture-aware install of the docker CLI, upx, and docker-buildx.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)   upx_arch=amd64_linux;  bx_arch=linux-amd64;   docker_arch=x86_64 ;; \
      aarch64)  upx_arch=arm64_linux;  bx_arch=linux-arm64;   docker_arch=aarch64 ;; \
      armv7l)   upx_arch=arm_linux;    bx_arch=linux-arm-v7;  docker_arch=armhf ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_VERSION}.tgz" \
      | tar -xz -C /tmp docker/docker; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker; \
    curl -fsSL "https://github.com/upx/upx/releases/download/v${UPX_VERSION}/upx-${UPX_VERSION}-${upx_arch}.tar.xz" \
      | tar -xJ -C /tmp; \
    install -m 0755 "/tmp/upx-${UPX_VERSION}-${upx_arch}/upx" /usr/local/bin/upx; \
    rm -rf "/tmp/upx-${UPX_VERSION}-${upx_arch}"; \
    mkdir -p /root/.docker/cli-plugins; \
    curl -fsSL -o /root/.docker/cli-plugins/docker-buildx \
      "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.${bx_arch}"; \
    chmod +x /root/.docker/cli-plugins/docker-buildx; \
    docker --version; \
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

# No USER directive: the container runs as root by design.
#   - `--runtime docker` (default) needs the host's Docker socket mounted at
#     /var/run/docker.sock, which is typically root-owned on the host.
#   - The Docker CLI's buildx plugin is installed under /root/.docker/cli-plugins.
# Users who don't need the daemon path should prefer `--output-oci PATH`, which
# emits an OCI archive without touching the socket and can be combined with
# `docker run --user $(id -u):$(id -g)` to drop privileges.
ENTRYPOINT ["dockerize"]
CMD ["--help"]
