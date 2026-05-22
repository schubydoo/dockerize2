"""``dockerize`` command-line entry point."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __description__, __program__, __version__
from .compress import CompressionLevel
from .dockerize import DEFAULT_NSS_MODULES, Dockerize, SymlinkOptions
from .sbom import SBOMFormat

__all__ = ["FILETOOLS", "CliArgs", "main", "parse_args"]

LOG = logging.getLogger(__name__)

# Common file-manipulation tools added by --filetools. Stored as bare names
# and resolved against the host PATH with shutil.which() at runtime, so this
# works on systems where these tools don't live under /bin (e.g. non-FHS
# layouts like NixOS, or distros that split /bin and /usr/bin differently).
FILETOOLS: list[str] = [
    "ls",
    "mkdir",
    "chmod",
    "chown",
    "rm",
    "cat",
    "grep",
    "sed",
]


@dataclass
class CliArgs:
    """Parsed and validated command-line arguments."""

    paths: list[str]
    tag: str | None
    cmd: str | None
    entrypoint: str | None
    no_build: bool
    output_dir: str | None
    add_file: list[tuple[str, str]]
    symlinks: SymlinkOptions
    user: list[str] = field(default_factory=list)
    group: list[str] = field(default_factory=list)
    filetools: bool = False
    runtime: str = "docker"
    buildcmd: str = "build"
    loglevel: int = logging.WARN
    no_host_lookup: bool = False
    allow_sensitive: bool = False
    nss_modules: tuple[str, ...] = DEFAULT_NSS_MODULES
    extra_labels: dict[str, str] = field(default_factory=dict)
    compress_level: CompressionLevel | None = None
    compress_libs: bool = False
    sbom_path: Path | None = None
    sbom_format: SBOMFormat = SBOMFormat.SPDX_JSON
    output_oci: Path | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__description__)

    docker_group = parser.add_argument_group("Docker options")
    docker_group.add_argument("--tag", "-t", help="Tag to apply to Docker image")
    docker_group.add_argument("--cmd", "-c")
    docker_group.add_argument("--entrypoint", "-e")

    output_group = parser.add_argument_group("Output options")
    output_group.add_argument(
        "--no-build",
        "-n",
        action="store_true",
        help="Do not build Docker image",
    )
    output_group.add_argument("--output-dir", "-o")

    parser.add_argument(
        "--add-file",
        "-a",
        metavar=("SRC", "DST"),
        nargs=2,
        action="append",
        default=[],
        help="Add file <src> to image at <dst>",
    )

    parser.add_argument(
        "--symlinks",
        "-L",
        default="copy-unsafe",
        help="One of preserve, copy-unsafe, skip-unsafe, copy-all",
    )
    parser.add_argument(
        "--user",
        "-u",
        action="append",
        default=[],
        help="Add user to /etc/passwd in image",
    )
    parser.add_argument(
        "--group",
        "-g",
        action="append",
        default=[],
        help="Add group to /etc/group in image",
    )

    parser.add_argument(
        "--filetools",
        action="store_true",
        help="Add common file manipulation tools",
    )

    security_group = parser.add_argument_group("Security options")
    security_group.add_argument(
        "--no-host-lookup",
        action="store_true",
        help="Reject bare user/group names; require colon-delimited entries.",
    )
    security_group.add_argument(
        "--allow-sensitive",
        action="store_true",
        help="Allow copying known-sensitive host paths (/etc/shadow, ~/.ssh/*, etc.).",
    )
    security_group.add_argument(
        "--nss-modules",
        default=",".join(DEFAULT_NSS_MODULES),
        help=(
            "Comma-separated list of nss modules to copy into the image "
            "(default: files,dns). Limits CVE surface vs. copying every libnss*."
        ),
    )
    security_group.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Add an OCI image label. Repeatable.",
    )

    compress_group = parser.add_argument_group("Compression options")
    compress_group.add_argument(
        "--compress",
        action="store_true",
        help="Apply UPX compression to ELF executables in the image.",
    )
    compress_group.add_argument(
        "--compress-level",
        choices=[level.value for level in CompressionLevel],
        default="best",
        help="UPX level when --compress is set (default: best).",
    )
    compress_group.add_argument(
        "--compress-libs",
        action="store_true",
        help=(
            "Also compress shared libraries (deprecated UPX feature; "
            "increases incompatibility risk — use at your own risk)."
        ),
    )

    output_more = parser.add_argument_group("Output options (advanced)")
    output_more.add_argument(
        "--sbom",
        metavar="PATH",
        default=None,
        help="Write an SBOM of the build context to PATH (requires syft).",
    )
    output_more.add_argument(
        "--sbom-format",
        choices=[fmt.value for fmt in SBOMFormat],
        default=SBOMFormat.SPDX_JSON.value,
        help="SBOM format (default: spdx-json).",
    )
    output_more.add_argument(
        "--output-oci",
        metavar="PATH",
        default=None,
        help=(
            "Emit an OCI image archive to PATH instead of loading the image "
            "into a local store. Uses `docker buildx`, whose default `docker` "
            "driver only exports OCI when the daemon's containerd image store "
            "is enabled (otherwise create a `docker buildx create --driver "
            "docker-container` builder); falls back to daemonless `podman save "
            "--format oci-archive`. The benefit is the portable OCI archive, "
            "not avoiding the daemon."
        ),
    )

    parser.add_argument(
        "--runtime",
        "-R",
        help="Set container engine for building",
        default="docker",
    )
    parser.add_argument(
        "--buildcmd",
        "-B",
        help="Set command for building",
        default="build",
    )

    log_group = parser.add_argument_group("Logging options")
    log_group.add_argument(
        "--verbose",
        action="store_const",
        const=logging.INFO,
        dest="loglevel",
    )
    log_group.add_argument(
        "--debug",
        action="store_const",
        const=logging.DEBUG,
        dest="loglevel",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{__program__} version {__version__}",
    )
    parser.add_argument("paths", nargs=argparse.REMAINDER)
    parser.set_defaults(loglevel=logging.WARN)

    return parser


def parse_args(argv: list[str] | None = None) -> CliArgs:
    """Parse and validate ``argv`` (or ``sys.argv``) into a :class:`CliArgs`."""
    parser = _build_parser()
    ns = parser.parse_args(argv)

    try:
        symlinks = SymlinkOptions[ns.symlinks.upper().replace("-", "_")]
    except KeyError:
        parser.error(f"{ns.symlinks}: invalid symlink mode")

    # If a single binary was given and no entrypoint, use the binary.
    entrypoint = ns.entrypoint
    if len(ns.paths) == 1 and not entrypoint:
        entrypoint = ns.paths[0]

    nss_modules = tuple(m.strip() for m in ns.nss_modules.split(",") if m.strip())

    extra_labels: dict[str, str] = {}
    for raw in ns.label:
        if "=" not in raw:
            parser.error(f"--label {raw!r}: expected KEY=VALUE")
        key, value = raw.split("=", 1)
        extra_labels[key.strip()] = value

    compress_level = CompressionLevel(ns.compress_level) if ns.compress else None
    sbom_path = Path(ns.sbom) if ns.sbom else None
    sbom_format = SBOMFormat(ns.sbom_format)
    output_oci = Path(ns.output_oci) if ns.output_oci else None

    return CliArgs(
        paths=list(ns.paths),
        tag=ns.tag,
        cmd=ns.cmd,
        entrypoint=entrypoint,
        no_build=ns.no_build,
        output_dir=ns.output_dir,
        add_file=[(src, dst) for src, dst in ns.add_file],
        symlinks=symlinks,
        user=list(ns.user),
        group=list(ns.group),
        filetools=ns.filetools,
        runtime=ns.runtime,
        buildcmd=ns.buildcmd,
        loglevel=ns.loglevel,
        no_host_lookup=ns.no_host_lookup,
        allow_sensitive=ns.allow_sensitive,
        nss_modules=nss_modules,
        extra_labels=extra_labels,
        compress_level=compress_level,
        compress_libs=ns.compress_libs,
        sbom_path=sbom_path,
        sbom_format=sbom_format,
        output_oci=output_oci,
    )


def main(argv: list[str] | None = None) -> None:
    """``dockerize`` console-script entry point.

    ``dockerize doctor`` dispatches to the doctor subcommand. Any other
    invocation falls through to the classic CLI.
    """
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "doctor":
        from .doctor import run

        sys.exit(run())

    args = parse_args(argv)
    logging.basicConfig(level=args.loglevel)

    app = Dockerize(
        cmd=args.cmd,
        runtime=args.runtime,
        buildcmd=args.buildcmd,
        entrypoint=args.entrypoint,
        tag=args.tag,
        targetdir=args.output_dir,
        build=not args.no_build,
        symlinks=args.symlinks,
        no_host_lookup=args.no_host_lookup,
        allow_sensitive=args.allow_sensitive,
        nss_modules=args.nss_modules,
        extra_labels=args.extra_labels,
        compress_level=args.compress_level,
        compress_libs=args.compress_libs,
        sbom_path=args.sbom_path,
        sbom_format=args.sbom_format,
        output_oci=args.output_oci,
    )

    for path in args.paths:
        app.add_file(path)

    for src, dst in args.add_file:
        app.add_file(src, dst)

    if args.filetools:
        for name in FILETOOLS:
            resolved = shutil.which(name)
            if resolved is None:
                LOG.warning("--filetools: %r not found on PATH; skipping", name)
                continue
            app.add_file(resolved)

    for user in args.user:
        app.add_user(user)

    for group in args.group:
        app.add_group(group)

    app.build()


if __name__ == "__main__":
    main()
