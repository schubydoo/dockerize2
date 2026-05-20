"""Unit tests for ``dockerize.depsolver``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from elftools.common.exceptions import ELFError

from dockerize import depsolver


def test_read_interpreter_returns_none_for_non_elf(tmp_path: Path) -> None:
    text = tmp_path / "not_elf.txt"
    text.write_text("hello world")
    assert depsolver._read_interpreter(text) is None


def test_read_interpreter_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert depsolver._read_interpreter(tmp_path / "nope") is None


def test_read_interpreter_returns_none_for_static_elf(tmp_path: Path) -> None:
    """ELF magic but no .interp section => statically linked, fast-path None."""
    fake = tmp_path / "static.elf"
    fake.write_bytes(b"\x7fELF" + b"\x00" * 200)

    fake_elf = MagicMock()
    fake_elf.get_section_by_name.return_value = None
    with patch.object(depsolver, "ELFFile", return_value=fake_elf):
        assert depsolver._read_interpreter(fake) is None


def test_read_interpreter_returns_path_for_dynamic_elf(tmp_path: Path) -> None:
    fake = tmp_path / "dynamic.elf"
    fake.write_bytes(b"\x7fELF" + b"\x00" * 200)

    fake_section = MagicMock()
    fake_section.data.return_value = b"/lib64/ld-linux-x86-64.so.2\x00"
    fake_elf = MagicMock()
    fake_elf.get_section_by_name.return_value = fake_section
    with patch.object(depsolver, "ELFFile", return_value=fake_elf):
        assert depsolver._read_interpreter(fake) == "/lib64/ld-linux-x86-64.so.2"


def test_read_interpreter_handles_elferror(tmp_path: Path) -> None:
    fake = tmp_path / "broken.elf"
    fake.write_bytes(b"\x7fELF" + b"\x00" * 50)
    with patch.object(depsolver, "ELFFile", side_effect=ELFError("malformed")):
        assert depsolver._read_interpreter(fake) is None


def test_depsolver_add_nonexistent_path() -> None:
    d = depsolver.DepSolver()
    d.add("/this/path/does/not/exist")
    assert d.deps == set()


def test_depsolver_static_binary_fast_path(tmp_path: Path) -> None:
    """A static binary contributes zero deps and never calls the dynamic loader."""
    binary = tmp_path / "static_bin"
    binary.write_bytes(b"\x7fELF" + b"\x00" * 200)

    with (
        patch.object(depsolver, "_read_interpreter", return_value=None),
        patch("subprocess.check_output") as run,
    ):
        d = depsolver.DepSolver()
        d.add(binary)
        assert d.deps == set()
        run.assert_not_called()


def test_depsolver_dynamic_binary_collects_deps(tmp_path: Path) -> None:
    binary = tmp_path / "dynamic_bin"
    binary.write_bytes(b"\x7fELF" + b"\x00" * 200)
    interp = "/lib64/ld-linux-x86-64.so.2"

    loader_output = (
        "\tlinux-vdso.so.1 (0x00007ffdb1d8e000)\n"
        "\tlibc.so.6 => /lib64/libc.so.6 (0x00007f2a3a000000)\n"
        "\t/lib64/ld-linux-x86-64.so.2 (0x00007f2a3a3a0000)\n"
    )
    with (
        patch.object(depsolver, "_read_interpreter", return_value=interp),
        patch("subprocess.check_output", return_value=loader_output),
    ):
        d = depsolver.DepSolver()
        d.add(binary)

    assert interp in d.deps
    assert "/lib64/libc.so.6" in d.deps
    # An entry without a "=>" arrow is also captured by the second regex.
    assert "/lib64/ld-linux-x86-64.so.2" in d.deps


def test_depsolver_prefixes() -> None:
    d = depsolver.DepSolver()
    d.deps = {
        "/lib/x86_64-linux-gnu/libc.so.6",
        "/lib/x86_64-linux-gnu/libm.so.6",
        "/lib64/ld-linux-x86-64.so.2",
    }
    assert d.prefixes() == {
        "/lib/x86_64-linux-gnu",
        "/lib64",
    }


def test_re_deps_matches_arrow_form() -> None:
    line = "\tlibc.so.6 => /lib64/libc.so.6 (0x00007f2a3a000000)"
    m = depsolver.RE_DEPS[0].match(line)
    assert m is not None
    assert m.group("path") == "/lib64/libc.so.6"


def test_re_deps_second_pattern_no_leading_whitespace() -> None:
    """The fallback regex anchors at start; lines like ``\\tld-linux ...`` do not
    match it. That's fine because the interpreter is added explicitly. This
    test pins that behaviour so the regex can't drift unnoticed."""
    line = "/lib64/ld-linux-x86-64.so.2 (0x00007f2a3a3a0000)"
    m = depsolver.RE_DEPS[1].match(line)
    assert m is not None
    assert m.group("path") == "/lib64/ld-linux-x86-64.so.2"
