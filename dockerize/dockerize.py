"""Core ``Dockerize`` orchestration: copy files, resolve deps, render templates."""

from __future__ import annotations

import glob
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from enum import Enum

from jinja2 import Environment, PackageLoader

from .depsolver import DepSolver

LOG = logging.getLogger(__name__)


class SymlinkOptions(Enum):
    """How ``rsync``/``shutil`` should treat symlinks when copying into the image."""

    PRESERVE = 1
    COPY_UNSAFE = 2
    SKIP_UNSAFE = 3
    COPY_ALL = 4


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

        self.targetdir: str | None = targetdir
        self.symlinks: SymlinkOptions = symlinks
        self._build_image: bool = build

        self.users: list[str] = []
        self.groups: list[str] = []
        self.paths: set[tuple[str, str]] = set()
        self.env: Environment = Environment(loader=PackageLoader("dockerize", "templates"))

    def add_user(self, user: str) -> None:
        """Import a user into ``/etc/passwd`` on the image.

        Accepts a username (looked up via ``getpwnam``) or a colon-delimited
        password entry used verbatim. The lookup path is Linux-only; passing a
        colon-delimited entry works on any platform.
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

        Accepts a group name (looked up via ``getgrnam``) or a colon-delimited
        group entry used verbatim. The lookup path is Linux-only; passing a
        colon-delimited entry works on any platform.
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

        Creates (or reuses) ``targetdir``, copies queued files and their shared-lib
        dependencies, renders ``/etc/passwd``/``/etc/group``/``Dockerfile``, then
        invokes ``<runtime> build`` unless ``build=False`` was passed.
        """
        LOG.info("start build process")
        cleanup = False
        try:
            if not self.targetdir:
                self.targetdir = tempfile.mkdtemp(prefix="dockerize")
                cleanup = True
            else:
                LOG.warning("writing output to %s", self.targetdir)
                if not os.path.isdir(self.targetdir):
                    os.mkdir(self.targetdir)

            self.copy_files()
            self.resolve_deps()
            self.populate()
            self.generate_dockerfile()
            if self._build_image:
                self.build_image()
        finally:
            if cleanup and self.targetdir:
                shutil.rmtree(self.targetdir, ignore_errors=True)

    def generate_dockerfile(self) -> None:
        LOG.info("generating Dockerfile")
        assert self.targetdir is not None
        tmpl = self.env.get_template("Dockerfile")
        with open(os.path.join(self.targetdir, "Dockerfile"), "w") as fde:
            fde.write(tmpl.render(controller=self, docker=self.docker))

    def makedirs(self, path: str) -> None:
        if not os.path.isdir(path):
            os.makedirs(path)

    def populate(self) -> None:
        """Render and write ``/etc/passwd``, ``/etc/group``, ``nsswitch.conf``."""
        LOG.info("populating misc config files")
        assert self.targetdir is not None
        self.makedirs(os.path.join(self.targetdir, "etc"))
        for path in ["passwd", "group", "nsswitch.conf"]:
            tmpl = self.env.get_template(path)
            with open(os.path.join(self.targetdir, "etc", path), "w") as fde:
                fde.write(
                    tmpl.render(
                        controller=self,
                        docker=self.docker,
                        users=self.users,
                        groups=self.groups,
                    )
                )

    def copy_file(
        self,
        src: str,
        dst: str | None = None,
        symlinks: SymlinkOptions | None = None,
    ) -> None:
        """Copy a file (or directory tree) into the image via ``rsync -a``."""
        if dst is None:
            dst = src

        if symlinks is None:
            symlinks = self.symlinks

        LOG.info("copying file %s to %s", src, dst)
        assert self.targetdir is not None
        target = os.path.join(self.targetdir, dst[1:])
        target_dir = os.path.dirname(target)
        self.makedirs(target_dir)

        cmd: list[str] = ["rsync", "-a"]

        if symlinks == SymlinkOptions.COPY_ALL:
            cmd.append("-L")
        elif symlinks == SymlinkOptions.COPY_UNSAFE:
            cmd.append("--copy-unsafe-links")
        elif symlinks == SymlinkOptions.SKIP_UNSAFE:
            cmd.append("--safe-links")

        cmd += [src, target]

        LOG.info("running: %s", cmd)
        subprocess.check_call(cmd)

    def resolve_deps(self) -> None:
        """Walk the image tree and pull in shared-library dependencies."""
        deps = DepSolver()
        assert self.targetdir is not None

        for root, _, files in os.walk(self.targetdir):
            for name in files:
                path = os.path.join(root, name)
                deps.add(path)

        for src in deps.deps:
            self.copy_file(src, symlinks=SymlinkOptions.COPY_ALL)

        # Install basic nss libraries so resolver lookups work in the image.
        for libdir in deps.prefixes():
            for nsslib in os.listdir(libdir):
                if nsslib.startswith("libnss") or nsslib.startswith("libresolv"):
                    src = os.path.join(libdir, nsslib)
                    LOG.info("copying %s", src)
                    self.copy_file(src, symlinks=SymlinkOptions.COPY_ALL)

    def copy_files(self) -> None:
        """Copy every file queued via :py:meth:`add_file` into the image."""
        for src, dst in self.paths:
            for srcitem in glob.iglob(src):
                self.copy_file(srcitem, dst)

    def build_image(self) -> None:
        cmd: list[str] = [self.docker["runtime"], self.docker["buildcmd"]]
        if "tag" in self.docker:
            cmd += ["-t", self.docker["tag"]]
        assert self.targetdir is not None
        cmd += [self.targetdir]

        LOG.info('building Docker image using "%s"', " ".join(cmd))
        subprocess.check_call(cmd)
