"""End-to-end integration tests.

These build a real Docker image from a real binary and require ``docker`` or
``podman`` on the host. They run only when ``--run-integration`` is passed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dockerize.compress import CompressionLevel
from dockerize.dockerize import Dockerize, SymlinkOptions
from dockerize.sbom import SBOMFormat

integration_only = pytest.mark.integration

linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="integration tests require a Linux host"
)


@integration_only
@linux_only
def test_build_image_from_bin_ls(tmp_path: Path) -> None:
    """Build an image from /bin/ls and assert it runs."""
    runtime = shutil.which("docker") or shutil.which("podman")
    if runtime is None:
        pytest.skip("no docker/podman on PATH")

    out = tmp_path / "image"
    app = Dockerize(
        targetdir=str(out),
        tag="dockerize2-test-ls:integration",
        entrypoint="/bin/ls",
        symlinks=SymlinkOptions.COPY_ALL,
        build=False,  # render only; build step run separately below
    )
    app.add_file("/bin/ls")
    app.build()

    # Confirm scaffolding is in place
    assert (out / "Dockerfile").exists()
    assert (out / "etc" / "passwd").exists()
    assert (out / "bin" / "ls").exists()

    # Now build the image
    subprocess.check_call([runtime, "build", "-t", "dockerize2-test-ls:integration", str(out)])
    # And run it
    result = subprocess.check_output(
        [runtime, "run", "--rm", "dockerize2-test-ls:integration", "/"],
        text=True,
    )
    assert "etc" in result or "bin" in result


@integration_only
@linux_only
def test_build_with_compress_actually_compresses(tmp_path: Path) -> None:
    """End-to-end: --compress should produce a UPX-compressed binary in the image."""
    if shutil.which("upx") is None:
        pytest.skip("upx not installed")

    out = tmp_path / "image"
    app = Dockerize(
        targetdir=str(out),
        tag="dockerize2-test-compress:integration",
        entrypoint="/bin/ls",
        symlinks=SymlinkOptions.COPY_ALL,
        compress_level=CompressionLevel.NORMAL,  # fastest level for CI
        build=False,
    )
    app.add_file("/bin/ls")
    app.build()

    # UPX-packed binaries carry the "UPX!" magic in their first few KB.
    packed = (out / "bin" / "ls").read_bytes()
    assert b"UPX!" in packed[:4096], "binary doesn't appear to be UPX-compressed"


@integration_only
@linux_only
def test_output_oci_runs_buildx_path(tmp_path: Path) -> None:
    """End-to-end: --output-oci drives the real docker buildx OCI path.

    The unit tests in test_sbom_and_oci.py mock subprocess, so this is the
    only place the daemon-backed buildx OCI path actually runs. Whether it
    succeeds depends on the daemon: buildx's default ``docker`` driver only
    exports OCI when the containerd image store is enabled. Both outcomes are
    valid and asserted here:

    * containerd store / container driver available -> a valid OCI archive;
    * stock daemon -> an actionable ``OciOutputError`` (NOT an opaque
      ``CalledProcessError``).
    """
    from dockerize.oci_output import OciOutputError

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker not on PATH")
    if subprocess.run([docker, "buildx", "version"], capture_output=True).returncode != 0:
        pytest.skip("docker buildx not available")

    ctx = tmp_path / "ctx"
    archive = tmp_path / "image.oci.tar"
    app = Dockerize(
        targetdir=str(ctx),
        tag="dockerize2-test-oci:integration",
        entrypoint="/bin/ls",
        symlinks=SymlinkOptions.COPY_ALL,
        output_oci=archive,
    )
    app.add_file("/bin/ls")

    try:
        app.build()
    except OciOutputError as err:
        # Stock daemon without the containerd image store: the failure must be
        # actionable, naming the way out — not a bare CalledProcessError.
        message = str(err)
        assert "containerd image store" in message
        assert "docker-container" in message
        return

    # Daemon can export OCI: the archive must be a real OCI image layout, i.e.
    # an oci-layout marker plus an index.json whose first manifest digest
    # resolves to a blob present in the archive.
    import tarfile

    assert archive.exists() and archive.stat().st_size > 0
    with tarfile.open(archive) as tf:
        names = set(tf.getnames())
        assert "oci-layout" in names
        assert "index.json" in names
        index_member = tf.extractfile("index.json")
        assert index_member is not None
        index = json.loads(index_member.read())

    manifests = index["manifests"]
    assert manifests, "OCI index declares no manifests"
    algo, _, hexdigest = manifests[0]["digest"].partition(":")
    assert f"blobs/{algo}/{hexdigest}" in names, "manifest blob missing from archive"


@integration_only
@linux_only
def test_build_with_sbom_writes_spdx(tmp_path: Path) -> None:
    """End-to-end: --sbom should produce a parseable SPDX JSON file."""
    if shutil.which("syft") is None:
        pytest.skip("syft not installed")

    out = tmp_path / "image"
    sbom_path = tmp_path / "sbom.spdx.json"
    app = Dockerize(
        targetdir=str(out),
        tag="dockerize2-test-sbom:integration",
        entrypoint="/bin/ls",
        symlinks=SymlinkOptions.COPY_ALL,
        sbom_path=sbom_path,
        sbom_format=SBOMFormat.SPDX_JSON,
        build=False,
    )
    app.add_file("/bin/ls")
    app.build()

    assert sbom_path.exists()
    data = json.loads(sbom_path.read_text())
    # SPDX 2.x documents declare spdxVersion; SPDX 3.x uses @context.
    assert "spdxVersion" in data or "@context" in data, (
        f"output doesn't look like SPDX JSON; top-level keys: {sorted(data.keys())[:6]}"
    )
