# syntax=docker/dockerfile:1.7

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
# Stage 2: runtime.
#
# Tools installed from upstream releases rather than Debian apt:
#   - upx           : --compress (Debian's upx-ucl trails upstream + non-free
#                     status varies across mirrors)
#   - docker-buildx : --output-oci (not packaged in bookworm main)
#   - syft          : --sbom (anchore install script, multi-arch)
# Why upstream tarballs: clean, latest version, predictable across the three
# target arches (linux/amd64, linux/arm64, linux/arm/v7).
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

# Architecture-aware install of upx, docker-buildx, and syft.
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
    curl -fsSL https://raw.githubusercontent.com/anchore/syft/main/install.sh \
      | sh -s -- -b /usr/local/bin; \
    upx --version; \
    docker buildx version; \
    syft version

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
