"""``dockerize`` command-line entry point."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field

from . import __description__, __program__, __version__
from .dockerize import Dockerize, SymlinkOptions

LOG = logging.getLogger(__name__)

FILETOOLS: list[str] = [
    "/bin/ls",
    "/bin/mkdir",
    "/bin/chmod",
    "/bin/chown",
    "/bin/rm",
    "/bin/cat",
    "/bin/grep",
    "/bin/sed",
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
    )


def main(argv: list[str] | None = None) -> None:
    """``dockerize`` console-script entry point."""
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
    )

    for path in args.paths:
        app.add_file(path)

    for src, dst in args.add_file:
        app.add_file(src, dst)

    if args.filetools:
        for path in FILETOOLS:
            app.add_file(path)

    for user in args.user:
        app.add_user(user)

    for group in args.group:
        app.add_group(group)

    app.build()


if __name__ == "__main__":
    main()
