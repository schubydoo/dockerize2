"""Resolve shared-library dependencies of dynamic ELF binaries."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import NamedTuple

LOG = logging.getLogger(__name__)

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


class ELFContents(NamedTuple):
    # ``idx`` instead of ``index`` because ``tuple.index`` is a built-in method.
    idx: str
    name: str
    size: str
    vma: str
    lma: str
    offset: str
    aligment: str


class ELFFile(dict[str, ELFContents]):
    """Lightweight wrapper over ``objdump -h`` output for a single ELF file."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path: str = path
        self.read_sections()

    def read_sections(self) -> None:
        """Use ``objdump`` to read the section table from the ELF file."""
        try:
            out = subprocess.check_output(
                ["objdump", "-h", self.path],
                stderr=subprocess.STDOUT,
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError(self.path) from exc

        for line in out.splitlines():
            line = line.strip()
            if not line or not line[0].isdigit():
                continue

            contents = ELFContents(*line.split())
            self[contents.name] = contents

    def section(self, name: str) -> bytes:
        """Return the raw bytes of the named section from the ELF file."""
        section = self[name]
        with open(self.path, "rb") as fde:
            fde.seek(int(section.offset, base=16))
            data = fde.read(int(section.size, base=16))
            return data

    def interpreter(self) -> str:
        """Return the value of the ``.interp`` section (the dynamic loader path)."""
        return self.section(".interp").rstrip(b"\0").decode("utf-8")


class DepSolver:
    """Walks ELF binaries and accumulates their shared-library dependencies."""

    def __init__(self) -> None:
        self.deps: set[str] = set()

    def get_deps(self, path: str) -> None:
        LOG.info("getting dependencies for %s", path)

        # The dynamic loader (.interp) is needed because we invoke it with
        # --list to enumerate the binary's dependencies (this is how ldd works).
        try:
            elf = ELFFile(path)
            interp = elf.interpreter()
        except ValueError:
            LOG.debug("%s is not a dynamically linked ELF binary (ignoring)", path)
            return
        except KeyError:
            LOG.debug("%s does not have a .interp section", path)
            return

        self.deps.add(interp)
        out = subprocess.check_output([interp, "--list", path], encoding="utf-8")

        for line in out.splitlines():
            for exp in RE_DEPS:
                match = exp.match(line)
                if not match:
                    continue

                dep = match.group("path")
                LOG.debug("%s requires %s", path, dep)
                self.deps.add(dep)

    def add(self, path: str) -> None:
        """Append the dependencies of ``path`` to :attr:`deps`."""
        self.get_deps(path)

    def prefixes(self) -> set[str]:
        """Return the set of directory prefixes containing accumulated deps."""
        return {os.path.dirname(p) for p in self.deps}
