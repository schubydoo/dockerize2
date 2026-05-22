"""Assemble an OCI image archive natively, without a container daemon.

dockerize only ever produces a single-layer ``FROM scratch`` image — the staged
root filesystem plus ``ENTRYPOINT``/``CMD``/labels — so the OCI image can be
built in pure Python instead of shelling out to ``docker buildx``. We tar+gzip
the staging directory into one layer blob, then write the image config, an image
manifest, ``index.json`` and ``oci-layout`` per the OCI image-layout spec, and
package the whole layout as a tar archive.

The result is the same OCI image-layout archive that
``docker buildx build --output type=oci`` produced, but needs no daemon, no
buildx and no podman — so ``--output-oci`` now works anywhere Python runs, and
the runtime image no longer bundles the docker-buildx plugin.

Consume the archive with ``skopeo copy oci-archive:img.tar ...``, ``oras``,
``podman load``, containerd's ``ctr image import``, or ``docker load`` on a
daemon with the containerd image store enabled.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import logging
import os
import platform
import tarfile
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

__all__ = ["OciOutputError", "build_oci_archive"]

LOG = logging.getLogger(__name__)

_MEDIA_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
_MEDIA_CONFIG = "application/vnd.oci.image.config.v1+json"
_MEDIA_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
_MEDIA_INDEX = "application/vnd.oci.image.index.v1+json"

# Top-level build artifacts that must not leak into the image root filesystem.
# dockerize writes its generated Dockerfile into the staging directory; it is a
# build input, not part of the image.
_DEFAULT_EXCLUDES: frozenset[str] = frozenset({"Dockerfile"})

_CHUNK = 1024 * 1024


class OciOutputError(RuntimeError):
    """Raised when the OCI archive cannot be assembled."""


def _detect_oci_platform() -> tuple[str, str | None]:
    """Map the host machine to an ``(architecture, variant)`` OCI pair.

    dockerize copies the host's own ELF binaries into the image, so the image
    architecture is the architecture we are running on.
    """
    machine = platform.machine().lower()
    mapping: dict[str, tuple[str, str | None]] = {
        "x86_64": ("amd64", None),
        "amd64": ("amd64", None),
        "aarch64": ("arm64", None),
        "arm64": ("arm64", None),
        "armv7l": ("arm", "v7"),
        "armv6l": ("arm", "v6"),
        "i386": ("386", None),
        "i686": ("386", None),
        "ppc64le": ("ppc64le", None),
        "s390x": ("s390x", None),
        "riscv64": ("riscv64", None),
    }
    if machine in mapping:
        return mapping[machine]
    LOG.warning("unrecognized machine %r; defaulting OCI architecture to amd64", machine)
    return ("amd64", None)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_entries(root: Path, exclude_top: frozenset[str]) -> list[Path]:
    """Depth-first, name-sorted entries under ``root`` (symlinks not followed).

    Sorting yields a stable layer digest for identical trees; not following
    symlinks keeps the walk bounded and records links as links.
    """
    out: list[Path] = []

    def _recurse(directory: Path, *, top: bool) -> None:
        with os.scandir(directory) as scan:
            for entry in sorted(scan, key=lambda e: e.name):
                if top and entry.name in exclude_top:
                    continue
                path = Path(entry.path)
                out.append(path)
                if entry.is_dir(follow_symlinks=False):
                    _recurse(path, top=False)

    _recurse(root, top=True)
    return out


def _write_layer_tar(context_dir: Path, dest_tar: Path, exclude_top: frozenset[str]) -> None:
    """Tar ``context_dir`` into ``dest_tar`` with normalized, reproducible metadata."""
    with tarfile.open(dest_tar, mode="w") as tar:
        for path in _iter_entries(context_dir, exclude_top):
            arcname = path.relative_to(context_dir).as_posix()
            info = tar.gettarinfo(str(path), arcname=arcname)
            # Normalize for reproducible digests and to avoid leaking host
            # ownership/timestamps into the published image.
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if info.isreg():
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
            else:
                tar.addfile(info)


def _gzip_file(src: Path, dest: Path) -> None:
    """Gzip ``src`` to ``dest`` with no embedded name/timestamp (reproducible)."""
    with (
        src.open("rb") as fin,
        dest.open("wb") as fout,
        gzip.GzipFile(filename="", fileobj=fout, mode="wb", mtime=0) as gz,
    ):
        for chunk in iter(lambda: fin.read(_CHUNK), b""):
            gz.write(chunk)


def _json_blob(obj: dict[str, object]) -> bytes:
    """Serialize ``obj`` to compact, key-sorted JSON bytes (stable digests)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _descriptor(media_type: str, digest: str, size: int) -> dict[str, object]:
    return {"mediaType": media_type, "digest": digest, "size": size}


def _build_config(
    diff_id: str,
    *,
    entrypoint: Sequence[str] | None,
    cmd: Sequence[str] | None,
    labels: dict[str, str] | None,
    created: str,
    architecture: str,
    variant: str | None,
    os_name: str,
) -> bytes:
    config_section: dict[str, object] = {}
    if entrypoint:
        config_section["Entrypoint"] = list(entrypoint)
    if cmd:
        config_section["Cmd"] = list(cmd)
    if labels:
        config_section["Labels"] = dict(labels)

    image: dict[str, object] = {
        "created": created,
        "architecture": architecture,
        "os": os_name,
        "config": config_section,
        "rootfs": {"type": "layers", "diff_ids": [diff_id]},
        "history": [{"created": created, "created_by": "dockerize2: FROM scratch; COPY . /"}],
    }
    if variant:
        image["variant"] = variant
    return _json_blob(image)


def _pack_layout(layout_dir: Path, output_path: Path) -> None:
    """Tar an on-disk OCI image layout into ``output_path`` in a stable order."""
    with tarfile.open(output_path, mode="w") as tar:
        tar.add(layout_dir / "oci-layout", arcname="oci-layout")
        tar.add(layout_dir / "index.json", arcname="index.json")
        for blob in sorted((layout_dir / "blobs").rglob("*")):
            if blob.is_file():
                tar.add(blob, arcname=blob.relative_to(layout_dir).as_posix())


def build_oci_archive(
    context_dir: Path,
    output_path: Path,
    *,
    tag: str | None = None,
    entrypoint: Sequence[str] | None = None,
    cmd: Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
    created: str | None = None,
    architecture: str | None = None,
    os_name: str = "linux",
    exclude_top: Iterable[str] = _DEFAULT_EXCLUDES,
) -> Path:
    """Write a single-layer OCI image-layout archive of ``context_dir``.

    ``context_dir`` is the staged image root filesystem. Its top-level
    ``Dockerfile`` (dockerize's own build artifact) is excluded from the layer.
    ``entrypoint``/``cmd``/``labels`` populate the image config; ``tag``, when
    given, becomes the ``org.opencontainers.image.ref.name`` annotation on the
    manifest. ``architecture``/``os_name`` default to the host platform.

    Returns ``output_path``. Raises :class:`OciOutputError` if ``context_dir``
    is not a directory.
    """
    context_dir = Path(context_dir)
    output_path = Path(output_path)
    if not context_dir.is_dir():
        raise OciOutputError(f"OCI context directory does not exist: {context_dir}")

    if architecture is None:
        architecture, variant = _detect_oci_platform()
    else:
        variant = None
    if created is None:
        created = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    exclude = frozenset(exclude_top)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dockerize-oci-") as tmp:
        work = Path(tmp)
        blobs = work / "blobs" / "sha256"
        blobs.mkdir(parents=True)

        # 1. Layer blob: the uncompressed tar fixes the diffID; its gzip fixes
        #    the layer digest. Stream through temp files to bound memory.
        raw_tar = work / "layer.tar"
        _write_layer_tar(context_dir, raw_tar, exclude)
        diff_id = "sha256:" + _sha256_file(raw_tar)

        gz_tar = work / "layer.tar.gz"
        _gzip_file(raw_tar, gz_tar)
        raw_tar.unlink()
        layer_hex = _sha256_file(gz_tar)
        layer_size = gz_tar.stat().st_size
        gz_tar.rename(blobs / layer_hex)
        layer_digest = "sha256:" + layer_hex

        # 2. Image config blob.
        config_bytes = _build_config(
            diff_id,
            entrypoint=entrypoint,
            cmd=cmd,
            labels=labels,
            created=created,
            architecture=architecture,
            variant=variant,
            os_name=os_name,
        )
        config_hex = _sha256_bytes(config_bytes)
        (blobs / config_hex).write_bytes(config_bytes)
        config_digest = "sha256:" + config_hex

        # 3. Image manifest blob.
        manifest = {
            "schemaVersion": 2,
            "mediaType": _MEDIA_MANIFEST,
            "config": _descriptor(_MEDIA_CONFIG, config_digest, len(config_bytes)),
            "layers": [_descriptor(_MEDIA_LAYER, layer_digest, layer_size)],
        }
        manifest_bytes = _json_blob(manifest)
        manifest_hex = _sha256_bytes(manifest_bytes)
        (blobs / manifest_hex).write_bytes(manifest_bytes)
        manifest_digest = "sha256:" + manifest_hex

        # 4. Top-level index + layout marker.
        manifest_desc = _descriptor(_MEDIA_MANIFEST, manifest_digest, len(manifest_bytes))
        platform_obj: dict[str, object] = {"architecture": architecture, "os": os_name}
        if variant:
            platform_obj["variant"] = variant
        manifest_desc["platform"] = platform_obj
        if tag:
            manifest_desc["annotations"] = {"org.opencontainers.image.ref.name": tag}

        index = {
            "schemaVersion": 2,
            "mediaType": _MEDIA_INDEX,
            "manifests": [manifest_desc],
        }
        (work / "index.json").write_bytes(_json_blob(index))
        (work / "oci-layout").write_bytes(_json_blob({"imageLayoutVersion": "1.0.0"}))

        # 5. Package the layout as the output archive.
        _pack_layout(work, output_path)

    LOG.info("wrote OCI image archive -> %s", output_path)
    return output_path
