"""Unit tests for ``dockerize.sbom`` and ``dockerize.oci_output``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dockerize import oci_output
from dockerize.oci_output import OciOutputError, build_oci_archive
from dockerize.sbom import SBOMFormat, SyftNotFoundError, find_syft, generate_sbom

# -------- syft -------------------------------------------------------------


def test_find_syft_missing() -> None:
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(SyftNotFoundError, match="not found on PATH"),
    ):
        find_syft()


def test_find_syft_resolved() -> None:
    with patch("shutil.which", return_value="/usr/local/bin/syft"):
        assert find_syft() == "/usr/local/bin/syft"


def test_generate_sbom_invokes_syft(tmp_path: Path) -> None:
    source = tmp_path / "ctx"
    source.mkdir()
    output = tmp_path / "sbom.spdx.json"

    with patch("subprocess.check_call") as run:
        generate_sbom(source, output, syft_path="/usr/bin/syft")

    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/syft"
    assert f"dir:{source}" in argv
    assert f"spdx-json={output}" in argv


def test_generate_sbom_alternate_format(tmp_path: Path) -> None:
    source = tmp_path / "ctx"
    source.mkdir()
    output = tmp_path / "sbom.json"

    with patch("subprocess.check_call") as run:
        generate_sbom(
            source,
            output,
            sbom_format=SBOMFormat.CYCLONEDX_JSON,
            syft_path="/usr/bin/syft",
        )
    argv = run.call_args.args[0]
    assert f"cyclonedx-json={output}" in argv


# -------- OCI output ------------------------------------------------------


def test_oci_output_uses_docker_buildx_when_available(tmp_path: Path) -> None:
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    out = tmp_path / "image.oci.tar"

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch.object(oci_output, "_has_buildx", return_value=True),
        patch("subprocess.check_call") as run,
    ):
        build_oci_archive(ctx, out, tag="img:1")

    argv = run.call_args.args[0]
    assert "/usr/bin/docker" in argv
    assert "buildx" in argv
    assert f"type=oci,dest={out}" in argv
    assert "-t" in argv
    assert "img:1" in argv


def test_oci_output_falls_back_to_podman(tmp_path: Path) -> None:
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    out = tmp_path / "image.oci.tar"

    def which_side_effect(cmd: str) -> str | None:
        return "/usr/bin/podman" if cmd == "podman" else None

    with (
        patch("shutil.which", side_effect=which_side_effect),
        patch.object(oci_output, "_has_buildx", return_value=False),
        patch("subprocess.check_call") as run,
    ):
        build_oci_archive(ctx, out, tag="img:1")

    # Two podman invocations: build then save.
    assert run.call_count == 2
    build_argv, save_argv = run.call_args_list[0].args[0], run.call_args_list[1].args[0]
    assert "build" in build_argv
    assert "save" in save_argv
    assert "oci-archive" in save_argv


def test_oci_output_no_engine_raises(tmp_path: Path) -> None:
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    out = tmp_path / "image.oci.tar"
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(OciOutputError, match="docker buildx"),
    ):
        build_oci_archive(ctx, out)


# -------- CLI plumbing ----------------------------------------------------


def test_cli_sbom_flag_populates_path() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--sbom", "/tmp/sbom.json", "/bin/ls"])
    assert args.sbom_path == Path("/tmp/sbom.json")
    assert args.sbom_format is SBOMFormat.SPDX_JSON


def test_cli_sbom_format_choice() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--sbom", "x.json", "--sbom-format", "cyclonedx-json", "/bin/ls"])
    assert args.sbom_format is SBOMFormat.CYCLONEDX_JSON


def test_cli_output_oci_populates_path() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--output-oci", "/tmp/img.oci.tar", "/bin/ls"])
    assert args.output_oci == Path("/tmp/img.oci.tar")
