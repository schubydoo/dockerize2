"""Core ``Dockerize`` orchestration: copy files, resolve deps, render templates."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
from enum import Enum
from pathlib import Path

from jinja2 import Environment, PackageLoader

from .depsolver import DepSolver

LOG = logging.getLogger(__name__)


class SymlinkOptions(Enum):
    """How symlinks are handled when copying files into the image."""

    PRESERVE = 1
    COPY_UNSAFE = 2
    SKIP_UNSAFE = 3
    COPY_ALL = 4


def _is_unsafe_symlink(link: Path) -> bool:
    """An "unsafe" symlink resolves outside its own parent directory.

    Mirrors rsync's ``--safe-links`` semantics closely enough for our purposes:
    absolute symlinks and symlinks whose target escapes the link's parent are
    treated as unsafe.
    """
    raw = link.readlink()
    if raw.is_absolute():
        return True
    parent = link.parent.resolve()
    target = (link.parent / raw).resolve(strict=False)
    return parent != target and parent not in target.parents


def _copy_symlink(src: Path, dst: Path) -> None:
    """Replicate a symlink at ``dst`` pointing at ``src``'s target."""
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src.readlink())


def _expand_glob(pattern: str) -> list[Path]:
    """Expand a possibly-absolute glob pattern into matching ``Path`` objects.

    If the pattern is a literal path (no metacharacters) and the file exists,
    the path is returned as-is. Otherwise the pattern is interpreted via
    :py:meth:`Path.glob` rooted at ``/`` (absolute pattern) or the cwd.
    """
    has_meta = any(ch in pattern for ch in "*?[")
    if not has_meta:
        return [Path(pattern)]

    p = Path(pattern)
    if p.is_absolute():
        # Path.glob requires a relative pattern from the anchor.
        anchor = Path(p.anchor)
        rel = pattern[len(p.anchor) :]
        return list(anchor.glob(rel))
    return list(Path.cwd().glob(pattern))


class Dockerize:
    """Build a minimal Docker image from a set of dynamically linked binaries."""

    def __init__(
        self,
        cmd: str | None = None,
        entrypoint: str | None = None,
        targetdir: str | None = None,
        tag: str | None = None,
        runtime: str | None = None,
        buildcmd: str | None = None,
        symlinks: SymlinkOptions = SymlinkOptions.PRESERVE,
        build: bool = True,
    ) -> None:
        self.docker: dict[str, str] = {
            "runtime": runtime if runtime else "docker",
            "buildcmd": buildcmd if buildcmd else "build",
        }

        if cmd:
            self.docker["cmd"] = json.dumps(shlex.split(cmd))
            LOG.debug("CMD: %s", self.docker["cmd"])
        if entrypoint:
            self.docker["entrypoint"] = json.dumps(shlex.split(entrypoint))
            LOG.debug("ENTRYPOINT: %s", self.docker["entrypoint"])
        if tag:
            self.docker["tag"] = tag
            LOG.debug("tag: %s", self.docker["tag"])

        self.targetdir: Path | None = Path(targetdir) if targetdir else None
        self.symlinks: SymlinkOptions = symlinks
        self._build_image: bool = build

        self.users: list[str] = []
        self.groups: list[str] = []
        self.paths: set[tuple[str, str]] = set()
        self.env: Environment = Environment(loader=PackageLoader("dockerize", "templates"))

    def add_user(self, user: str) -> None:
        """Import a user into ``/etc/passwd`` on the image.

        Accepts a username (looked up via ``getpwnam`` — Linux-only) or a
        colon-delimited password entry used verbatim (any platform).
        """
        LOG.info("adding user %s", user)
        if ":" in user:
            self.users.append(user)
            return

        import grp
        import pwd

        pwent = pwd.getpwnam(user)  # type: ignore[attr-defined, unused-ignore]
        self.users.append(":".join(str(x) for x in pwent))
        grent = grp.getgrgid(pwent.pw_gid)  # type: ignore[attr-defined, unused-ignore]
        self.groups.append(
            ":".join(str(x) for x in (*grent[:3], ",".join(grent[3])) if not isinstance(x, list))
        )

    def add_group(self, group: str) -> None:
        """Import a group into ``/etc/group`` on the image.

        Accepts a group name (Linux-only) or a colon-delimited entry used
        verbatim (any platform).
        """
        LOG.info("adding group %s", group)
        if ":" in group:
            self.groups.append(group)
            return

        import grp

        grent = grp.getgrnam(group)  # type: ignore[attr-defined, unused-ignore]
        self.groups.append(":".join(str(x) for x in grent))

    def add_file(self, src: str, dst: str | None = None) -> None:
        """Queue a file to be installed into the image."""
        if dst is None:
            dst = src

        if not dst.startswith("/"):
            raise ValueError(f"{dst}: container paths must be fully qualified")

        self.paths.add((src, dst))

    def build(self) -> None:
        """Produce a Docker image.

        Creates (or reuses) ``targetdir``, copies queued files and their
        shared-lib dependencies, renders ``/etc/passwd``/``/etc/group``/
        ``Dockerfile``, then invokes ``<runtime> build`` unless
        ``build=False`` was passed.
        """
        LOG.info("start build process")
        cleanup = False
        try:
            if self.targetdir is None:
                self.targetdir = Path(tempfile.mkdtemp(prefix="dockerize"))
                cleanup = True
            else:
                LOG.warning("writing output to %s", self.targetdir)
                self.targetdir.mkdir(parents=True, exist_ok=True)

            self.copy_files()
            self.resolve_deps()
            self.populate()
            self.generate_dockerfile()
            if self._build_image:
                self.build_image()
        finally:
            if cleanup and self.targetdir is not None:
                shutil.rmtree(self.targetdir, ignore_errors=True)

    def generate_dockerfile(self) -> None:
        LOG.info("generating Dockerfile")
        assert self.targetdir is not None
        tmpl = self.env.get_template("Dockerfile")
        (self.targetdir / "Dockerfile").write_text(tmpl.render(controller=self, docker=self.docker))

    def populate(self) -> None:
        """Render and write ``/etc/passwd``, ``/etc/group``, ``nsswitch.conf``."""
        LOG.info("populating misc config files")
        assert self.targetdir is not None
        etc_dir = self.targetdir / "etc"
        etc_dir.mkdir(parents=True, exist_ok=True)
        for path in ["passwd", "group", "nsswitch.conf"]:
            tmpl = self.env.get_template(path)
            (etc_dir / path).write_text(
                tmpl.render(
                    controller=self,
                    docker=self.docker,
                    users=self.users,
                    groups=self.groups,
                )
            )

    def copy_file(
        self,
        src: str | Path,
        dst: str | None = None,
        symlinks: SymlinkOptions | None = None,
    ) -> None:
        """Copy a file or directory tree into the image.

        Uses ``shutil`` (no host ``rsync`` required). ``symlinks`` selects how
        symlinks encountered during the copy are treated.
        """
        src_path = Path(src)
        if dst is None:
            dst = str(src)
        if symlinks is None:
            symlinks = self.symlinks

        LOG.info("copying %s to %s", src_path, dst)
        assert self.targetdir is not None
        target = self.targetdir / dst.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)

        follow = symlinks in (SymlinkOptions.COPY_ALL, SymlinkOptions.COPY_UNSAFE)

        if src_path.is_dir() and not src_path.is_symlink():
            self._copy_tree(src_path, target, symlinks)
            return

        if (
            symlinks == SymlinkOptions.SKIP_UNSAFE
            and src_path.is_symlink()
            and _is_unsafe_symlink(src_path)
        ):
            LOG.debug("skipping unsafe symlink %s", src_path)
            return

        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()

        if src_path.is_symlink() and not follow:
            _copy_symlink(src_path, target)
        else:
            shutil.copy2(src_path, target, follow_symlinks=follow)

    def _copy_tree(self, src: Path, dst: Path, mode: SymlinkOptions) -> None:
        """Recursive copy with symlink handling matching ``mode``."""
        preserve_links = mode != SymlinkOptions.COPY_ALL

        if dst.exists() and not dst.is_symlink():
            shutil.rmtree(dst)
        elif dst.is_symlink():
            dst.unlink()

        if mode in (SymlinkOptions.PRESERVE, SymlinkOptions.COPY_ALL):
            shutil.copytree(src, dst, symlinks=preserve_links)
            return

        # COPY_UNSAFE / SKIP_UNSAFE need per-symlink decisions.
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            entry_dst = dst / entry.name
            if entry.is_symlink():
                if _is_unsafe_symlink(entry):
                    if mode == SymlinkOptions.SKIP_UNSAFE:
                        LOG.debug("skipping unsafe symlink %s", entry)
                        continue
                    # COPY_UNSAFE: dereference into a real file/dir copy
                    if entry.is_dir():
                        shutil.copytree(entry, entry_dst, symlinks=False)
                    else:
                        shutil.copy2(entry, entry_dst, follow_symlinks=True)
                else:
                    _copy_symlink(entry, entry_dst)
            elif entry.is_dir():
                self._copy_tree(entry, entry_dst, mode)
            else:
                shutil.copy2(entry, entry_dst, follow_symlinks=False)

    def resolve_deps(self) -> None:
        """Walk the image tree and pull in shared-library dependencies."""
        deps = DepSolver()
        assert self.targetdir is not None

        for root, _, files in os.walk(self.targetdir):
            for name in files:
                path = Path(root) / name
                deps.add(path)

        for src in deps.deps:
            self.copy_file(src, symlinks=SymlinkOptions.COPY_ALL)

        # Install basic nss libraries so resolver lookups work in the image.
        for libdir in deps.prefixes():
            libdir_path = Path(libdir)
            if not libdir_path.is_dir():
                continue
            for nsslib in libdir_path.iterdir():
                name = nsslib.name
                if name.startswith("libnss") or name.startswith("libresolv"):
                    LOG.info("copying %s", nsslib)
                    self.copy_file(nsslib, symlinks=SymlinkOptions.COPY_ALL)

    def copy_files(self) -> None:
        """Copy every file queued via :py:meth:`add_file` into the image."""
        for src, dst in self.paths:
            for srcitem in _expand_glob(src):
                self.copy_file(srcitem, dst)

    def build_image(self) -> None:
        import subprocess

        cmd: list[str] = [self.docker["runtime"], self.docker["buildcmd"]]
        if "tag" in self.docker:
            cmd += ["-t", self.docker["tag"]]
        assert self.targetdir is not None
        cmd += [str(self.targetdir)]

        LOG.info('building Docker image using "%s"', " ".join(cmd))
        subprocess.check_call(cmd)
