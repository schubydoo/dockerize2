"""Emit an OCI image archive.

Uses ``docker buildx build --output type=oci,dest=<path>`` (or ``podman build
--format oci`` followed by ``podman save``). The output is a portable OCI
archive rather than an image loaded into a local store.

Note: the ``docker buildx`` path needs more than a reachable daemon. buildx's
default ``docker`` driver can only export an OCI archive when the daemon has
the containerd image store enabled; on a stock daemon it fails with "OCI
exporter is not supported for the docker driver". The alternatives are a
container-based builder (``docker buildx create --use --driver
docker-container``, which itself needs the daemon) or the daemonless ``podman``
fallback (``--runtime podman``). When buildx export fails, this module raises
:class:`OciOutputError` with that guidance.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

__all__ = ["OciOutputError", "build_oci_archive"]

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
        try:
            subprocess.check_call(argv)
        except subprocess.CalledProcessError as err:
            # The most common failure: buildx's default `docker` driver only
            # supports the OCI exporter when the daemon has the containerd
            # image store enabled. On a stock daemon the build aborts with
            # "OCI exporter is not supported for the docker driver". docker's
            # own stderr is already on the console; add an actionable hint.
            raise OciOutputError(
                "`docker buildx build --output type=oci` failed. The default "
                "`docker` buildx driver can only export an OCI archive when the "
                "daemon's containerd image store is enabled. Enable the "
                "containerd image store, create a container-based builder "
                "(`docker buildx create --use --driver docker-container`), or "
                "build with the daemonless `--runtime podman`. See docker's "
                "error above for the underlying cause."
            ) from err
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
