"""End-to-end integration tests.

These build a real Docker image from a real binary and require ``docker`` or
``podman`` on the host. They run only when ``--run-integration`` is passed.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
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
def test_output_oci_writes_native_archive(tmp_path: Path) -> None:
    """End-to-end: --output-oci assembles a valid OCI image-layout archive from
    a real binary build — no docker, no buildx, no daemon.

    The unit tests in test_sbom_and_oci.py exercise the writer with synthetic
    contexts; this is the regression baseline for the full pipeline against a
    real staged root filesystem (the binary plus its resolved shared libraries).
    """

    def _member_bytes(tf: tarfile.TarFile, name: str) -> bytes:
        member = tf.extractfile(name)
        assert member is not None, f"{name} missing from archive"
        return member.read()

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
    app.build()

    assert archive.exists() and archive.stat().st_size > 0
    with tarfile.open(archive) as tf:
        names = set(tf.getnames())
        assert "oci-layout" in names
        assert "index.json" in names

        index = json.loads(_member_bytes(tf, "index.json"))
        manifests = index["manifests"]
        assert manifests, "OCI index declares no manifests"
        algo, _, hexd = manifests[0]["digest"].partition(":")
        assert f"blobs/{algo}/{hexd}" in names, "manifest blob missing from archive"

        manifest = json.loads(_member_bytes(tf, f"blobs/{algo}/{hexd}"))
        config_algo, _, config_hex = manifest["config"]["digest"].partition(":")
        layer_algo, _, layer_hex = manifest["layers"][0]["digest"].partition(":")
        assert f"blobs/{config_algo}/{config_hex}" in names, "config blob missing"
        assert f"blobs/{layer_algo}/{layer_hex}" in names, "layer blob missing"
        config = json.loads(_member_bytes(tf, f"blobs/{config_algo}/{config_hex}"))
        layer_gz = _member_bytes(tf, f"blobs/{layer_algo}/{layer_hex}")

    # diffID integrity: the config's rootfs digest is the sha256 of the
    # uncompressed layer tar.
    raw = gzip.decompress(layer_gz)
    assert config["rootfs"]["diff_ids"] == ["sha256:" + hashlib.sha256(raw).hexdigest()]

    # The real binary landed in the layer; the generated Dockerfile did not.
    with tarfile.open(fileobj=io.BytesIO(raw)) as layer:
        layer_names = set(layer.getnames())
    assert "bin/ls" in layer_names
    assert "Dockerfile" not in layer_names
    assert config["config"]["Entrypoint"] == ["/bin/ls"]


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
