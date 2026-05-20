"""Core ``Dockerize`` orchestration: copy files, resolve deps, render templates."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import shlex
import shutil
import tempfile
from enum import Enum
from pathlib import Path

from jinja2 import Environment, PackageLoader

from . import __version__
from .compress import CompressionLevel, compress_tree
from .depsolver import DepSolver
from .oci_output import build_oci_archive
from .sbom import SBOMFormat, generate_sbom
from .security import is_sensitive_path

DEFAULT_NSS_MODULES: tuple[str, ...] = ("files", "dns")
PROJECT_SOURCE_URL = "https://github.com/schubydoo/dockerize2"

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


def _log_rmtree_error(_func: object, path: object, exc_info: object) -> None:
    """``shutil.rmtree`` error callback: log instead of silently swallowing."""
    LOG.warning("failed to remove %s during cleanup: %s", path, exc_info)


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
        no_host_lookup: bool = False,
        allow_sensitive: bool = False,
        nss_modules: tuple[str, ...] = DEFAULT_NSS_MODULES,
        extra_labels: dict[str, str] | None = None,
        compress_level: CompressionLevel | None = None,
        compress_libs: bool = False,
        sbom_path: Path | None = None,
        sbom_format: SBOMFormat = SBOMFormat.SPDX_JSON,
        output_oci: Path | None = None,
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
        self.no_host_lookup: bool = no_host_lookup
        self.allow_sensitive: bool = allow_sensitive
        self.nss_modules: tuple[str, ...] = tuple(nss_modules)
        self.extra_labels: dict[str, str] = dict(extra_labels or {})
        self.compress_level: CompressionLevel | None = compress_level
        self.compress_libs: bool = compress_libs
        self.sbom_path: Path | None = sbom_path
        self.sbom_format: SBOMFormat = sbom_format
        self.output_oci: Path | None = output_oci

        self.users: list[str] = []
        self.groups: list[str] = []
        self.paths: set[tuple[str, str]] = set()
        self.env: Environment = Environment(loader=PackageLoader("dockerize", "templates"))

    def add_user(self, user: str) -> None:
        """Import a user into ``/etc/passwd`` on the image.

        Accepts a username (looked up via ``getpwnam`` — Linux-only) or a
        colon-delimited password entry used verbatim. When ``no_host_lookup``
        is true, bare names are rejected so host ``/etc/passwd`` cannot leak
        into the image.
        """
        LOG.info("adding user %s", user)
        if ":" in user:
            self.users.append(user)
            return

        if self.no_host_lookup:
            raise ValueError(f"{user!r}: --no-host-lookup is set; provide a colon-delimited entry")

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
        verbatim. When ``no_host_lookup`` is true, bare names are rejected.
        """
        LOG.info("adding group %s", group)
        if ":" in group:
            self.groups.append(group)
            return

        if self.no_host_lookup:
            raise ValueError(f"{group!r}: --no-host-lookup is set; provide a colon-delimited entry")

        import grp

        grent = grp.getgrnam(group)  # type: ignore[attr-defined, unused-ignore]
        self.groups.append(":".join(str(x) for x in grent))

    def add_file(self, src: str, dst: str | None = None) -> None:
        """Queue a file to be installed into the image.

        Refuses host paths matching known sensitive patterns (``/etc/shadow``,
        SSH/AWS/Docker/kube credentials, etc.) unless ``allow_sensitive`` is
        true. This guards against accidental credential leakage into the
        resulting image.
        """
        if dst is None:
            dst = src

        if not dst.startswith("/"):
            raise ValueError(f"{dst}: container paths must be fully qualified")

        if not self.allow_sensitive and is_sensitive_path(src):
            raise ValueError(
                f"{src}: refused as sensitive host path. Pass --allow-sensitive to override."
            )

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
            self.compress()
            self.populate()
            self.generate_dockerfile()
            if self.sbom_path is not None:
                self.generate_sbom()
            if self._build_image:
                self.build_image()
        finally:
            if cleanup and self.targetdir is not None:
                shutil.rmtree(self.targetdir, onerror=_log_rmtree_error)

    def generate_dockerfile(self) -> None:
        LOG.info("generating Dockerfile")
        assert self.targetdir is not None
        tmpl = self.env.get_template("Dockerfile")
        (self.targetdir / "Dockerfile").write_text(
            tmpl.render(controller=self, docker=self.docker, labels=self.oci_labels())
        )

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

        # Install nss libraries matching the configured allowlist so that
        # resolver lookups work in the image. ``libresolv*`` is always
        # included because the ``dns`` resolver depends on it transitively.
        allowed_nss_prefixes = tuple(f"libnss_{mod}" for mod in self.nss_modules)
        for libdir in deps.prefixes():
            libdir_path = Path(libdir)
            if not libdir_path.is_dir():
                continue
            for nsslib in libdir_path.iterdir():
                name = nsslib.name
                if name.startswith(allowed_nss_prefixes) or name.startswith("libresolv"):
                    LOG.info("copying %s", nsslib)
                    self.copy_file(nsslib, symlinks=SymlinkOptions.COPY_ALL)

    def copy_files(self) -> None:
        """Copy every file queued via :py:meth:`add_file` into the image."""
        for src, dst in self.paths:
            for srcitem in _expand_glob(src):
                self.copy_file(srcitem, dst)

    def compress(self) -> list[Path]:
        """Apply UPX compression to compressible binaries under ``targetdir``."""
        if self.compress_level is None:
            return []
        assert self.targetdir is not None
        return compress_tree(
            self.targetdir,
            level=self.compress_level,
            include_libs=self.compress_libs,
        )

    def generate_sbom(self) -> Path:
        """Run ``syft`` against the build context and write an SBOM."""
        assert self.targetdir is not None
        assert self.sbom_path is not None
        return generate_sbom(self.targetdir, self.sbom_path, sbom_format=self.sbom_format)

    def build_image(self) -> None:
        import subprocess

        assert self.targetdir is not None

        # --output-oci mode: emit an OCI archive without a docker daemon socket.
        if self.output_oci is not None:
            build_oci_archive(
                self.targetdir,
                self.output_oci,
                tag=self.docker.get("tag"),
                runtime=self.docker["runtime"],
            )
            return

        runtime_name = self.docker["runtime"]
        runtime_path = shutil.which(runtime_name)
        if runtime_path is None:
            raise FileNotFoundError(
                f"runtime {runtime_name!r} not found on PATH; "
                "install it or pass --runtime / --no-build."
            )

        cmd: list[str] = [runtime_path, self.docker["buildcmd"]]
        if "tag" in self.docker:
            cmd += ["-t", self.docker["tag"]]
        cmd += [str(self.targetdir)]

        LOG.info('building Docker image using "%s"', " ".join(cmd))
        subprocess.check_call(cmd)

    def oci_labels(self) -> dict[str, str]:
        """Return the OCI image labels that should be written to the Dockerfile."""
        labels: dict[str, str] = {
            "org.opencontainers.image.created": _dt.datetime.now(_dt.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "org.opencontainers.image.source": PROJECT_SOURCE_URL,
            "org.opencontainers.image.version": __version__,
            "org.opencontainers.image.title": self.docker.get("tag", "dockerize2-image"),
            "org.opencontainers.image.licenses": "GPL-3.0-or-later",
        }
        labels.update(self.extra_labels)
        return labels
