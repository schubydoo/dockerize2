"""Unit tests for ``dockerize.dockerize``."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dockerize.dockerize import Dockerize, SymlinkOptions, _expand_glob, _is_unsafe_symlink

linux_or_mac = pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks need elevated rights on Windows"
)


# -------- add_file / add_user / add_group ---------------------------------


def test_add_file_relative_dst_raises() -> None:
    app = Dockerize()
    with pytest.raises(ValueError, match="must be fully qualified"):
        app.add_file("/usr/bin/foo", "relative/path")


def test_add_file_records_pair() -> None:
    app = Dockerize()
    app.add_file("/usr/bin/foo", "/bin/foo")
    assert ("/usr/bin/foo", "/bin/foo") in app.paths


def test_add_file_defaults_dst_to_src() -> None:
    app = Dockerize()
    app.add_file("/usr/bin/foo")
    assert ("/usr/bin/foo", "/usr/bin/foo") in app.paths


def test_add_user_colon_form_skips_lookup() -> None:
    app = Dockerize()
    app.add_user("alice:x:1000:1000:Alice:/home/alice:/bin/sh")
    assert app.users == ["alice:x:1000:1000:Alice:/home/alice:/bin/sh"]
    assert app.groups == []


def test_add_group_colon_form_skips_lookup() -> None:
    app = Dockerize()
    app.add_group("staff:x:50:")
    assert app.groups == ["staff:x:50:"]


# -------- entrypoint / cmd / tag serialisation ----------------------------


def test_cmd_and_entrypoint_json_serialised() -> None:
    app = Dockerize(cmd="-d /var/www", entrypoint="/usr/sbin/thttpd -D", tag="img:1")
    assert app.docker["cmd"] == '["-d", "/var/www"]'
    assert app.docker["entrypoint"] == '["/usr/sbin/thttpd", "-D"]'
    assert app.docker["tag"] == "img:1"


def test_default_runtime_and_buildcmd() -> None:
    app = Dockerize()
    assert app.docker["runtime"] == "docker"
    assert app.docker["buildcmd"] == "build"


def test_custom_runtime_overrides_default() -> None:
    app = Dockerize(runtime="podman", buildcmd="image build")
    assert app.docker["runtime"] == "podman"
    assert app.docker["buildcmd"] == "image build"


# -------- generate_dockerfile / populate ----------------------------------


def test_generate_dockerfile_renders_entrypoint_and_cmd(tmp_path: Path) -> None:
    app = Dockerize(
        cmd="-d /var/www",
        entrypoint="/usr/sbin/thttpd -D",
        targetdir=str(tmp_path),
    )
    app.generate_dockerfile()
    content = (tmp_path / "Dockerfile").read_text()
    assert "FROM scratch" in content
    assert 'ENTRYPOINT ["/usr/sbin/thttpd", "-D"]' in content
    assert 'CMD ["-d", "/var/www"]' in content


def test_populate_writes_etc_files(tmp_path: Path) -> None:
    app = Dockerize(targetdir=str(tmp_path))
    app.add_user("alice:x:1000:1000:Alice:/home/alice:/bin/sh")
    app.add_group("staff:x:50:")
    app.populate()

    passwd = (tmp_path / "etc" / "passwd").read_text()
    group = (tmp_path / "etc" / "group").read_text()
    nss = (tmp_path / "etc" / "nsswitch.conf").read_text()
    assert "alice:x:1000" in passwd
    assert "staff:x:50:" in group
    assert "hosts:" in nss


# -------- copy_file -------------------------------------------------------


def test_copy_file_copies_regular_file(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello")
    target_dir = tmp_path / "image"
    target_dir.mkdir()

    app = Dockerize(targetdir=str(target_dir))
    app.copy_file(str(src), "/bin/src.bin")

    assert (target_dir / "bin" / "src.bin").read_bytes() == b"hello"


def test_copy_file_overwrites_existing(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"new")
    target_dir = tmp_path / "image"
    target_dir.mkdir()
    (target_dir / "bin").mkdir()
    (target_dir / "bin" / "src.bin").write_bytes(b"old")

    app = Dockerize(targetdir=str(target_dir))
    app.copy_file(str(src), "/bin/src.bin")
    assert (target_dir / "bin" / "src.bin").read_bytes() == b"new"


@linux_or_mac
def test_copy_file_preserve_keeps_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"data")
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    target_dir = tmp_path / "image"
    target_dir.mkdir()

    app = Dockerize(targetdir=str(target_dir), symlinks=SymlinkOptions.PRESERVE)
    app.copy_file(str(link), "/usr/bin/link.bin")

    dst = target_dir / "usr" / "bin" / "link.bin"
    assert dst.is_symlink()
    assert dst.readlink() == real


@linux_or_mac
def test_copy_file_copy_all_dereferences_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"data")
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    target_dir = tmp_path / "image"
    target_dir.mkdir()

    app = Dockerize(targetdir=str(target_dir), symlinks=SymlinkOptions.COPY_ALL)
    app.copy_file(str(link), "/usr/bin/link.bin")

    dst = target_dir / "usr" / "bin" / "link.bin"
    assert dst.is_file()
    assert not dst.is_symlink()
    assert dst.read_bytes() == b"data"


# -------- _is_unsafe_symlink ----------------------------------------------


@linux_or_mac
def test_unsafe_symlink_absolute_target(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(Path("/etc/passwd"))
    assert _is_unsafe_symlink(link) is True


@linux_or_mac
def test_safe_symlink_relative_within_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to("target")  # relative, in same dir
    assert _is_unsafe_symlink(link) is False


@linux_or_mac
def test_unsafe_symlink_relative_escapes_parent(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    link = sub / "link"
    link.symlink_to("../outside")  # escapes sub/
    assert _is_unsafe_symlink(link) is True


# -------- _expand_glob ----------------------------------------------------


def test_expand_glob_literal_path() -> None:
    out = _expand_glob("/usr/bin/foo")
    assert out == [Path("/usr/bin/foo")]


def test_expand_glob_pattern_matches(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_text("")
    (tmp_path / "b.bin").write_text("")
    (tmp_path / "skip.txt").write_text("")
    matches = sorted(_expand_glob(str(tmp_path / "*.bin")))
    assert matches == [tmp_path / "a.bin", tmp_path / "b.bin"]


# -------- build (mocked) --------------------------------------------------


def test_build_invokes_runtime(tmp_path: Path) -> None:
    app = Dockerize(targetdir=str(tmp_path), tag="img:test", runtime="podman")
    with patch("subprocess.check_call") as run:
        app.build_image()
    args = run.call_args.args[0]
    assert args[0] == "podman"
    assert args[1] == "build"
    assert "-t" in args
    assert "img:test" in args


# -------- copy_files / resolve_deps / build (mocked end-to-end) -----------


def test_copy_files_iterates_paths(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"data")
    target = tmp_path / "image"
    target.mkdir()

    app = Dockerize(targetdir=str(target))
    app.add_file(str(src), "/bin/src.bin")
    app.copy_files()
    assert (target / "bin" / "src.bin").read_bytes() == b"data"


@linux_or_mac
def test_resolve_deps_copies_deps_into_image(tmp_path: Path) -> None:
    """resolve_deps walks the image, asks DepSolver, copies each dep in.

    POSIX-only because copy_file uses absolute-path semantics that don't
    transplant onto Windows drive-letter paths.
    """
    target = tmp_path / "image"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "fakebin").write_bytes(b"\x7fELF" + b"\x00" * 100)

    libdir = tmp_path / "fakelib"
    libdir.mkdir()
    fake_libc = libdir / "libc.so.6"
    fake_libc.write_bytes(b"libc-bytes")
    fake_nss = libdir / "libnss_files.so.2"
    fake_nss.write_bytes(b"nss-bytes")

    from dockerize.depsolver import DepSolver

    def fake_add(self: DepSolver, path: object) -> None:
        self.deps.add(str(fake_libc))

    app = Dockerize(targetdir=str(target))
    with patch.object(DepSolver, "add", new=fake_add):
        app.resolve_deps()

    assert (target / str(fake_libc).lstrip("/")).read_bytes() == b"libc-bytes"
    assert (target / str(fake_nss).lstrip("/")).read_bytes() == b"nss-bytes"


def test_full_build_orchestration(tmp_path: Path) -> None:
    """build() runs copy_files -> resolve_deps -> populate -> generate_dockerfile."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"\x7fELF" + b"\x00" * 100)
    target = tmp_path / "image"

    app = Dockerize(
        targetdir=str(target),
        tag="img:test",
        entrypoint="/bin/src.bin",
        build=False,
    )
    app.add_file(str(src), "/bin/src.bin")

    from dockerize.depsolver import DepSolver

    with patch.object(DepSolver, "add"):
        app.build()

    assert (target / "Dockerfile").exists()
    assert (target / "etc" / "passwd").exists()
    assert (target / "etc" / "group").exists()
    assert (target / "etc" / "nsswitch.conf").exists()
    assert (target / "bin" / "src.bin").exists()


def test_build_with_temp_targetdir_cleans_up(tmp_path: Path) -> None:
    """When no targetdir is given, build creates a temp dir and removes it."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")

    app = Dockerize(build=False)
    app.add_file(str(src), "/bin/src.bin")

    from dockerize.depsolver import DepSolver

    with patch.object(DepSolver, "add"):
        app.build()
    # targetdir is reassigned to the tempdir; after build() it's been removed.
    assert app.targetdir is not None
    assert not Path(app.targetdir).exists()
