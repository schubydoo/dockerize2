"""Resolve shared-library dependencies of dynamic ELF binaries.

The .interp section is read with ``pyelftools`` (no host ``objdump`` required).
For binaries that have an .interp section we still invoke the dynamic loader
with ``--list`` to enumerate libc-resolved deps — this matches what ``ldd(1)``
does. Statically linked binaries (no .interp) take a fast path and are simply
skipped: there is nothing to copy alongside them.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path, PurePosixPath

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

LOG = logging.getLogger(__name__)

ELF_MAGIC = b"\x7fELF"

RE_DEPS: list[re.Pattern[str]] = [
    re.compile(
        r"""\s+ (?P<name>\S+) \s+ => \s+
            (?P<path>\S+) \s+ \((?P<address>0x[0-9a-f]+)\)""",
        re.VERBOSE,
    ),
    re.compile(
        r"""(?P<path>\S+) \s+ \((?P<address>0x[0-9a-f]+)\)""",
        re.VERBOSE,
    ),
]


def _read_interpreter(path: Path) -> str | None:
    """Return the dynamic-loader path from ``.interp``.

    Returns ``None`` for non-ELF files and for statically linked binaries
    (no ``.interp`` section). Errors during ELF parsing are treated as
    "not an ELF we can analyse" and return ``None`` too.
    """
    try:
        with path.open("rb") as fde:
            if fde.read(len(ELF_MAGIC)) != ELF_MAGIC:
                return None
            fde.seek(0)
            elf = ELFFile(fde)  # type: ignore[no-untyped-call]
            interp_section = elf.get_section_by_name(".interp")  # type: ignore[no-untyped-call]
            if interp_section is None:
                return None
            data: bytes = interp_section.data()
            return data.rstrip(b"\0").decode("utf-8")
    except (ELFError, OSError):
        return None


class DepSolver:
    """Walk ELF binaries and accumulate their shared-library dependencies."""

    def __init__(self) -> None:
        self.deps: set[str] = set()

    def get_deps(self, path: str | Path) -> None:
        """Resolve dependencies of ``path`` and merge them into :attr:`deps`."""
        p = Path(path)
        if not p.is_file():
            return

        LOG.info("getting dependencies for %s", p)

        interpreter = _read_interpreter(p)
        if interpreter is None:
            LOG.debug(
                "%s has no .interp section (static or non-ELF) — no deps to add",
                p,
            )
            return

        self.deps.add(interpreter)
        self._collect_dynamic_deps(p, interpreter)

    def _collect_dynamic_deps(self, path: Path, interpreter: str) -> None:
        """Invoke the dynamic loader with ``--list`` and harvest dep paths."""
        out = subprocess.check_output(
            [interpreter, "--list", str(path)],
            encoding="utf-8",
        )

        for line in out.splitlines():
            for exp in RE_DEPS:
                match = exp.match(line)
                if not match:
                    continue
                dep = match.group("path")
                LOG.debug("%s requires %s", path, dep)
                self.deps.add(dep)

    def add(self, path: str | Path) -> None:
        """Append the dependencies of ``path`` to :attr:`deps`."""
        self.get_deps(path)

    def prefixes(self) -> set[str]:
        """Return the set of directory prefixes containing accumulated deps.

        Always returns POSIX-style paths because the deps themselves are POSIX
        (they were emitted by a Linux dynamic loader).
        """
        return {str(PurePosixPath(p).parent) for p in self.deps}
