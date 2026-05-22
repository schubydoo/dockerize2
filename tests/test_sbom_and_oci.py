"""Unit tests for ``dockerize.sbom`` and ``dockerize.oci_output``."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dockerize.oci_output import OciOutputError, build_oci_archive
from dockerize.sbom import (
    SBOMFormat,
    SbomGenerationError,
    SyftNotFoundError,
    find_syft,
    generate_sbom,
)

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


def test_generate_sbom_failure_raises_actionable_error(tmp_path: Path) -> None:
    """A non-zero exit from syft surfaces as SbomGenerationError naming the
    tool + command (chained from CalledProcessError), not a bare error."""
    import subprocess

    source = tmp_path / "ctx"
    source.mkdir()
    output = tmp_path / "sbom.spdx.json"

    cpe = subprocess.CalledProcessError(2, "syft")
    with (
        patch("subprocess.check_call", side_effect=cpe),
        pytest.raises(SbomGenerationError, match="syft failed") as excinfo,
    ):
        generate_sbom(source, output, syft_path="/usr/bin/syft")
    assert excinfo.value.__cause__ is cpe


# -------- OCI output (native, daemonless) ---------------------------------


def _make_context(tmp_path: Path) -> Path:
    """A staging dir with files, a nested dir, and a Dockerfile (which must be
    excluded from the image layer)."""
    ctx = tmp_path / "ctx"
    (ctx / "bin").mkdir(parents=True)
    (ctx / "etc").mkdir(parents=True)
    (ctx / "bin" / "ls").write_bytes(b"\x7fELF fake binary")
    (ctx / "etc" / "passwd").write_text("root:x:0:0:root:/root:/sbin/nologin\n")
    (ctx / "Dockerfile").write_text("FROM scratch\nCOPY . /\n")
    return ctx


def _extract(tar: tarfile.TarFile, name: str) -> bytes:
    member = tar.extractfile(name)
    assert member is not None, f"{name} missing from archive"
    return member.read()


def _read_archive(archive: Path) -> dict:
    """Parse an OCI image-layout tar into its components."""
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        blobs = {
            name.split("/")[-1]: _extract(tar, name)
            for name in names
            if name.startswith("blobs/sha256/")
        }
        index = json.loads(_extract(tar, "index.json"))
        layout = json.loads(_extract(tar, "oci-layout"))
    return {"names": names, "blobs": blobs, "index": index, "layout": layout}


def _blob(parsed: dict, digest: str) -> bytes:
    return parsed["blobs"][digest.split(":")[1]]


def _manifest_and_config(parsed: dict) -> tuple[dict, dict]:
    manifests = parsed["index"]["manifests"]
    assert len(manifests) == 1
    manifest = json.loads(_blob(parsed, manifests[0]["digest"]))
    config = json.loads(_blob(parsed, manifest["config"]["digest"]))
    return manifest, config


def test_build_oci_archive_returns_path_and_layout(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    out = tmp_path / "image.oci.tar"

    result = build_oci_archive(ctx, out, tag="img:1")

    assert result == out
    assert out.exists() and out.stat().st_size > 0
    parsed = _read_archive(out)
    assert parsed["layout"] == {"imageLayoutVersion": "1.0.0"}
    assert "oci-layout" in parsed["names"]
    assert "index.json" in parsed["names"]


def test_build_oci_archive_digests_resolve(tmp_path: Path) -> None:
    """index -> manifest -> {config, layer}: every digest is the sha256 of the
    blob it names, every referenced blob is present, and sizes match."""
    ctx = _make_context(tmp_path)
    out = tmp_path / "image.oci.tar"
    build_oci_archive(ctx, out, tag="img:1")
    parsed = _read_archive(out)

    # Content-addressable integrity: each blob's filename == sha256(content).
    for hexname, content in parsed["blobs"].items():
        assert hashlib.sha256(content).hexdigest() == hexname

    manifests = parsed["index"]["manifests"]
    assert manifests[0]["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
    assert manifests[0]["platform"]["os"] == "linux"
    assert manifests[0]["annotations"]["org.opencontainers.image.ref.name"] == "img:1"

    manifest, config = _manifest_and_config(parsed)
    config_desc = manifest["config"]
    layer_desc = manifest["layers"][0]
    assert config_desc["mediaType"] == "application/vnd.oci.image.config.v1+json"
    assert layer_desc["mediaType"] == "application/vnd.oci.image.layer.v1.tar+gzip"
    assert config_desc["size"] == len(_blob(parsed, config_desc["digest"]))
    assert layer_desc["size"] == len(_blob(parsed, layer_desc["digest"]))

    # diffID is the sha256 of the *uncompressed* layer tar.
    raw = gzip.decompress(_blob(parsed, layer_desc["digest"]))
    assert config["rootfs"]["diff_ids"] == ["sha256:" + hashlib.sha256(raw).hexdigest()]


def test_build_oci_archive_layer_excludes_dockerfile(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    out = tmp_path / "image.oci.tar"
    build_oci_archive(ctx, out)
    parsed = _read_archive(out)

    manifest, _config = _manifest_and_config(parsed)
    raw = gzip.decompress(_blob(parsed, manifest["layers"][0]["digest"]))
    with tarfile.open(fileobj=io.BytesIO(raw)) as layer:
        layer_names = set(layer.getnames())

    assert "bin/ls" in layer_names
    assert "etc/passwd" in layer_names
    assert "Dockerfile" not in layer_names


def test_build_oci_archive_sets_entrypoint_cmd_labels(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    out = tmp_path / "image.oci.tar"
    build_oci_archive(
        ctx,
        out,
        entrypoint=["/bin/ls"],
        cmd=["-l"],
        labels={"org.opencontainers.image.title": "demo"},
        architecture="amd64",
    )
    _, config = _manifest_and_config(_read_archive(out))

    assert config["config"]["Entrypoint"] == ["/bin/ls"]
    assert config["config"]["Cmd"] == ["-l"]
    assert config["config"]["Labels"] == {"org.opencontainers.image.title": "demo"}
    assert config["architecture"] == "amd64"
    assert config["os"] == "linux"


def test_build_oci_archive_detects_host_arch(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    out = tmp_path / "image.oci.tar"
    build_oci_archive(ctx, out)  # no architecture -> host detection
    _, config = _manifest_and_config(_read_archive(out))

    assert config["architecture"] in {
        "amd64",
        "arm64",
        "arm",
        "386",
        "ppc64le",
        "s390x",
        "riscv64",
    }


def test_build_oci_archive_is_reproducible(tmp_path: Path) -> None:
    """Identical content + pinned ``created`` -> byte-identical blob set."""
    ctx = _make_context(tmp_path)
    a, b = tmp_path / "a.tar", tmp_path / "b.tar"
    kwargs = {"tag": "img:1", "created": "2020-01-01T00:00:00Z", "architecture": "amd64"}
    build_oci_archive(ctx, a, **kwargs)
    build_oci_archive(ctx, b, **kwargs)

    assert set(_read_archive(a)["blobs"]) == set(_read_archive(b)["blobs"])


def test_build_oci_archive_missing_context_raises(tmp_path: Path) -> None:
    with pytest.raises(OciOutputError, match="context directory"):
        build_oci_archive(tmp_path / "nope", tmp_path / "x.tar")


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
