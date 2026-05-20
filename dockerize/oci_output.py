"""Emit an OCI image archive without requiring a Docker daemon socket.

Uses ``docker buildx build --output type=oci,dest=<path>`` (or ``podman build
--format oci`` followed by ``podman save``). This lets ``dockerize`` run inside
a container without mounting ``/var/run/docker.sock``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

LOG = logging.getLogger(__name__)


class OciOutputError(FileNotFoundError):
    """Raised when no engine capable of producing an OCI archive is available."""


def _has_buildx(docker: str) -> bool:
    try:
        subprocess.check_call(
            [docker, "buildx", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def build_oci_archive(
    context_dir: Path,
    output_path: Path,
    *,
    tag: str | None = None,
    runtime: str | None = None,
) -> Path:
    """Build an OCI image archive at ``output_path`` from ``context_dir``.

    ``runtime`` selects the engine; when ``None``, prefer ``docker buildx`` and
    fall back to ``podman``.
    """
    docker = shutil.which(runtime or "docker")
    if docker is not None and _has_buildx(docker):
        argv = [
            docker,
            "buildx",
            "build",
            "--output",
            f"type=oci,dest={output_path}",
        ]
        if tag:
            argv += ["-t", tag]
        argv.append(str(context_dir))
        LOG.info("building OCI archive via docker buildx -> %s", output_path)
        subprocess.check_call(argv)
        return output_path

    podman = shutil.which("podman")
    if podman is not None:
        local_tag = tag or "dockerize2-oci-tmp:latest"
        LOG.info("building image with podman, then exporting OCI archive")
        subprocess.check_call([podman, "build", "-t", local_tag, str(context_dir)])
        subprocess.check_call(
            [podman, "save", "--format", "oci-archive", "-o", str(output_path), local_tag]
        )
        return output_path

    raise OciOutputError(
        "OCI archive output requires either `docker buildx` or `podman`; "
        "neither is available on PATH."
    )
