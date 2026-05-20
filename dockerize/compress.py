"""Apply UPX compression to ELF binaries inside a build context."""

from __future__ import annotations

import logging
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

LOG = logging.getLogger(__name__)

# UPX won't shrink anything smaller than this meaningfully, and the per-file
# overhead is dominated by spawn cost. Skip below this size.
MIN_COMPRESS_SIZE = 50 * 1024


class CompressionLevel(StrEnum):
    NORMAL = "normal"
    BEST = "best"
    ULTRA = "ultra"


_UPX_ARGS: dict[CompressionLevel, list[str]] = {
    CompressionLevel.NORMAL: ["-q"],
    CompressionLevel.BEST: ["-q", "--best"],
    CompressionLevel.ULTRA: ["-q", "--best", "--ultra-brute"],
}


class UpxNotFoundError(FileNotFoundError):
    """Raised when --compress is requested but ``upx`` is not on PATH."""


def find_upx() -> str:
    """Return the absolute path to ``upx``, or raise :class:`UpxNotFoundError`."""
    path = shutil.which("upx")
    if path is None:
        raise UpxNotFoundError(
            "upx not found on PATH. Install it via your package manager: "
            "`apt install upx-ucl` (Debian/Ubuntu), "
            "`brew install upx` (macOS), "
            "`pacman -S upx` (Arch), or "
            "https://upx.github.io"
        )
    return path


def _classify_elf(path: Path) -> tuple[bool, bool]:
    """Return ``(is_elf, has_interp)`` for ``path``.

    ``has_interp`` is True for typical executables (which carry an ``.interp``
    section pointing at their dynamic loader) and False for shared libraries
    and PIE executables built without one. We treat ``has_interp`` as a
    heuristic for "this is an executable, safe to UPX by default".
    """
    try:
        with path.open("rb") as fde:
            if fde.read(4) != b"\x7fELF":
                return (False, False)
            fde.seek(0)
            elf = ELFFile(fde)  # type: ignore[no-untyped-call]
            return (True, elf.get_section_by_name(".interp") is not None)  # type: ignore[no-untyped-call]
    except (ELFError, OSError):
        return (False, False)


def _is_already_compressed(upx: str, path: Path) -> bool:
    """Return True if ``path`` is already a UPX-compressed file."""
    result = subprocess.run(
        [upx, "-t", str(path)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _is_compressible(
    path: Path,
    *,
    include_libs: bool,
    min_size: int,
) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < min_size:
        return False

    is_elf, has_interp = _classify_elf(path)
    if not is_elf:
        return False
    # Shared library (no .interp); UPX on shared libs is deprecated — opt-in only.
    return has_interp or include_libs


def compress(
    files: list[Path],
    *,
    level: CompressionLevel = CompressionLevel.BEST,
    include_libs: bool = False,
    min_size: int = MIN_COMPRESS_SIZE,
    upx_path: str | None = None,
) -> list[Path]:
    """Compress each compressible file in-place. Returns the actually-compressed paths."""
    upx = upx_path or find_upx()
    compressed: list[Path] = []
    for f in files:
        if not _is_compressible(f, include_libs=include_libs, min_size=min_size):
            LOG.debug("skipping %s (not eligible for compression)", f)
            continue
        if _is_already_compressed(upx, f):
            LOG.debug("skipping %s (already UPX-compressed)", f)
            continue
        argv = [upx, *_UPX_ARGS[level], str(f)]
        LOG.info("compressing %s (%s)", f, level.value)
        try:
            subprocess.check_call(argv)
        except subprocess.CalledProcessError as exc:
            LOG.warning("upx failed on %s: %s", f, exc)
            continue
        compressed.append(f)
    return compressed


def compress_tree(
    root: Path,
    *,
    level: CompressionLevel = CompressionLevel.BEST,
    include_libs: bool = False,
    min_size: int = MIN_COMPRESS_SIZE,
) -> list[Path]:
    """Walk ``root`` and apply :func:`compress` to every eligible file."""
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    return compress(files, level=level, include_libs=include_libs, min_size=min_size)
