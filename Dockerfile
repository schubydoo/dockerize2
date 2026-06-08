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
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.11.17@sha256:03bdc89bb9798628846e60c3a9ad19006c8c3c724ccd2985a33145c039a0577b AS uv-source

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
FROM --platform=$BUILDPLATFORM golang:1.26-bookworm@sha256:5d2b868674b57c9e48cdd39e891acce4196b6926ca6d11e9c270a8f85106203d AS syft-builder
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
# Stage 4a: `slim` runtime — pure-Python dockerize2 only.
#
# Just the base, the libgnutls security patch, and the dockerize2 wheel + its
# Python deps. No docker CLI, no syft, no upx — so this tag does NOT support
# `--runtime docker`, `--sbom`, or `--compress`. It DOES support the fully
# daemonless paths:
#   - `dockerize -n -o DIR <bin>`   → stage a binary + its libs for a later
#     multi-stage `FROM scratch; COPY --from=stage DIR/ /` build;
#   - `dockerize --output-oci PATH` → write a portable OCI image archive.
# Published as `:slim` and `:X.Y[.Z]-slim`.
#
# Why the apt upgrades: the pinned base lags Debian's security archive, so we
# pull forward specific patched libs the scanners flag:
#   - libgnutls30: base ships 3.7.9-2+deb12u6; deb12u7 fixes the GnuTLS CVE
#     batch — CVE-2026-33845, CVE-2026-42010, and others.
#   - libgcrypt20: base ships 1.10.1-3; 1.10.1-3+deb12u1 (DSA-6294-1) fixes
#     CVE-2026-41989, a heap overflow / DoS via crafted ECDH ciphertext to
#     gcry_pk_decrypt.
# `--only-upgrade` (no exact pin) always moves forward, so each is a harmless
# no-op once the base catches up — unlike a pinned `=deb12u7`, which would fail
# the build by implying a downgrade. Drop a package once the base no longer lags.
# -----------------------------------------------------------------------------
FROM python:3.14-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb AS slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends -y --only-upgrade libgnutls30 libgcrypt20; \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

LABEL org.opencontainers.image.source="https://github.com/schubydoo/dockerize2" \
      org.opencontainers.image.title="dockerize2" \
      org.opencontainers.image.description="Pack a dynamically linked ELF binary and its deps into a minimal scratch image." \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.documentation="https://github.com/schubydoo/dockerize2#readme"

WORKDIR /work

# No USER directive: the container runs as root by design. The daemonless paths
# (`-n -o DIR`, `--output-oci`) need no socket; combine with
# `docker run --user $(id -u):$(id -g)` to drop privileges.
ENTRYPOINT ["dockerize"]
CMD ["--help"]

# -----------------------------------------------------------------------------
# Stage 4b: `full` runtime (DEFAULT — published as `:latest` + semver tags).
#
# slim + the optional-feature tooling, installed from upstream releases rather
# than Debian apt:
#   - docker (CLI)  : --runtime docker. ONLY the static client from
#                     download.docker.com, not the `docker.io` apt package —
#                     dockerize talks to the *host's* daemon over the mounted
#                     socket, so the bundled dockerd/containerd/runc would be
#                     ~170 MB of dead weight. Also far newer than bookworm's
#                     docker.io (20.10.x).
#   - upx           : --compress (Debian's upx-ucl trails upstream + non-free
#                     status varies across mirrors).
#   - syft          : --sbom (cross-compiled in the syft-builder stage above;
#                     anchore ships no linux/armv7 binary).
# `--output-oci` needs none of these. As the LAST stage, a target-less build
# produces this image.
#
# curl/xz-utils/ca-certificates are build-only: installed, used to fetch the
# docker CLI + upx, then purged within this single layer (a purge in a later
# layer can't reclaim an earlier layer's bytes). ca-certificates is kept (curl's
# trust store; harmless at runtime).
# -----------------------------------------------------------------------------
FROM slim AS full

ARG UPX_VERSION=5.1.1
ARG DOCKER_VERSION=29.5.2

RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends -y curl xz-utils ca-certificates; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)   upx_arch=amd64_linux;  docker_arch=x86_64 ;; \
      aarch64)  upx_arch=arm64_linux;  docker_arch=aarch64 ;; \
      armv7l)   upx_arch=arm_linux;    docker_arch=armhf ;; \
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
    docker --version; \
    upx --version; \
    apt-get purge -y curl xz-utils; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

# Syft cross-compiled from source in the syft-builder stage above.
COPY --from=syft-builder /out/syft /usr/local/bin/syft
RUN syft version
