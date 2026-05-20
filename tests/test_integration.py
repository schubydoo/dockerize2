"""End-to-end integration tests.

These build a real Docker image from a real binary and require ``docker`` or
``podman`` on the host. They run only when ``--run-integration`` is passed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dockerize.dockerize import Dockerize, SymlinkOptions

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
