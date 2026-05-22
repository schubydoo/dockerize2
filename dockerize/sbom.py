"""Generate SBOM artefacts via ``syft``."""

from __future__ import annotations

import logging
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

__all__ = [
    "SBOMFormat",
    "SbomGenerationError",
    "SyftNotFoundError",
    "find_syft",
    "generate_sbom",
]

LOG = logging.getLogger(__name__)


class SBOMFormat(StrEnum):
    SPDX_JSON = "spdx-json"
    CYCLONEDX_JSON = "cyclonedx-json"
    SYFT_JSON = "syft-json"


class SyftNotFoundError(FileNotFoundError):
    """Raised when ``--sbom`` is requested but ``syft`` is not on PATH."""


class SbomGenerationError(RuntimeError):
    """Raised when ``syft`` runs but exits non-zero while generating the SBOM."""


def find_syft() -> str:
    """Return the absolute path to ``syft``, or raise :class:`SyftNotFoundError`."""
    path = shutil.which("syft")
    if path is None:
        raise SyftNotFoundError(
            "syft not found on PATH. Install via https://github.com/anchore/syft "
            "(`brew install syft`, `apt install syft`, or the install script)."
        )
    return path


def generate_sbom(
    source: Path,
    output: Path,
    *,
    sbom_format: SBOMFormat = SBOMFormat.SPDX_JSON,
    syft_path: str | None = None,
) -> Path:
    """Run ``syft`` on ``source`` and write the SBOM to ``output``."""
    syft = syft_path or find_syft()
    LOG.info("generating SBOM (%s) via syft: %s -> %s", sbom_format.value, source, output)
    argv = [syft, f"dir:{source}", "-o", f"{sbom_format.value}={output}"]
    try:
        subprocess.check_call(argv)
    except subprocess.CalledProcessError as err:
        raise SbomGenerationError(
            f"syft failed (exit {err.returncode}) while generating the SBOM. "
            f"Command: {' '.join(argv)}. See syft's output above for the cause."
        ) from err
    return output
