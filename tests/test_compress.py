"""Unit tests for ``dockerize.compress``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dockerize import compress
from dockerize.compress import (
    MIN_COMPRESS_SIZE,
    CompressionLevel,
    UpxNotFoundError,
    _classify_elf,
    _is_compressible,
)

# -------- find_upx ---------------------------------------------------------


def test_find_upx_raises_when_missing() -> None:
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(UpxNotFoundError, match="not found on PATH"),
    ):
        compress.find_upx()


def test_find_upx_returns_resolved_path() -> None:
    with patch("shutil.which", return_value="/usr/bin/upx"):
        assert compress.find_upx() == "/usr/bin/upx"


# -------- _classify_elf ----------------------------------------------------


def test_classify_elf_non_elf(tmp_path: Path) -> None:
    text = tmp_path / "x.txt"
    text.write_text("hello")
    assert _classify_elf(text) == (False, False)


def test_classify_elf_static_binary(tmp_path: Path) -> None:
    """ELF magic with no .interp section -> is_elf=True, has_interp=False."""
    f = tmp_path / "static"
    f.write_bytes(b"\x7fELF" + b"\x00" * 200)
    fake_elf = MagicMock()
    fake_elf.get_section_by_name.return_value = None
    with patch.object(compress, "ELFFile", return_value=fake_elf):
        assert _classify_elf(f) == (True, False)


def test_classify_elf_executable(tmp_path: Path) -> None:
    f = tmp_path / "exe"
    f.write_bytes(b"\x7fELF" + b"\x00" * 200)
    fake_elf = MagicMock()
    fake_elf.get_section_by_name.return_value = object()
    with patch.object(compress, "ELFFile", return_value=fake_elf):
        assert _classify_elf(f) == (True, True)


# -------- _is_compressible -------------------------------------------------


def test_is_compressible_skips_small_files(tmp_path: Path) -> None:
    f = tmp_path / "small"
    f.write_bytes(b"\x7fELF" + b"\x00" * 100)
    assert _is_compressible(f, include_libs=False, min_size=MIN_COMPRESS_SIZE) is False


def test_is_compressible_skips_non_elf(tmp_path: Path) -> None:
    f = tmp_path / "big_text"
    f.write_bytes(b"x" * (MIN_COMPRESS_SIZE + 1))  # not ELF magic
    assert _is_compressible(f, include_libs=False, min_size=MIN_COMPRESS_SIZE) is False


def test_is_compressible_skips_lib_by_default(tmp_path: Path) -> None:
    f = tmp_path / "lib"
    f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))
    with patch.object(compress, "_classify_elf", return_value=(True, False)):
        assert _is_compressible(f, include_libs=False, min_size=MIN_COMPRESS_SIZE) is False
        # With --compress-libs the same file is eligible
        assert _is_compressible(f, include_libs=True, min_size=MIN_COMPRESS_SIZE) is True


def test_is_compressible_executable(tmp_path: Path) -> None:
    f = tmp_path / "exe"
    f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))
    with patch.object(compress, "_classify_elf", return_value=(True, True)):
        assert _is_compressible(f, include_libs=False, min_size=MIN_COMPRESS_SIZE) is True


# -------- compress ---------------------------------------------------------


def test_compress_invokes_upx_per_eligible_file(tmp_path: Path) -> None:
    f = tmp_path / "exe"
    f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))
    with (
        patch.object(compress, "_classify_elf", return_value=(True, True)),
        patch.object(compress, "_is_already_compressed", return_value=False),
        patch("subprocess.check_call") as run,
    ):
        out = compress.compress([f], level=CompressionLevel.BEST, upx_path="/usr/bin/upx")
    assert out == [f]
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/upx"
    assert "--best" in argv
    assert str(f) in argv


def test_compress_idempotent_skips_already_compressed(tmp_path: Path) -> None:
    f = tmp_path / "exe"
    f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))
    with (
        patch.object(compress, "_classify_elf", return_value=(True, True)),
        patch.object(compress, "_is_already_compressed", return_value=True),
        patch("subprocess.check_call") as run,
    ):
        out = compress.compress([f], upx_path="/usr/bin/upx")
    assert out == []
    run.assert_not_called()


@pytest.mark.parametrize(
    ("level", "expected_arg"),
    [
        (CompressionLevel.NORMAL, None),
        (CompressionLevel.BEST, "--best"),
        (CompressionLevel.ULTRA, "--ultra-brute"),
    ],
)
def test_compress_level_passes_correct_flags(
    tmp_path: Path, level: CompressionLevel, expected_arg: str | None
) -> None:
    f = tmp_path / "exe"
    f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))
    with (
        patch.object(compress, "_classify_elf", return_value=(True, True)),
        patch.object(compress, "_is_already_compressed", return_value=False),
        patch("subprocess.check_call") as run,
    ):
        compress.compress([f], level=level, upx_path="/usr/bin/upx")
    argv = run.call_args.args[0]
    if expected_arg is not None:
        assert expected_arg in argv
    else:
        assert "--best" not in argv
        assert "--ultra-brute" not in argv


def test_compress_tree_walks_recursively(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    f1 = tmp_path / "exe1"
    f2 = tmp_path / "sub" / "exe2"
    for f in (f1, f2):
        f.write_bytes(b"\x7fELF" + b"\x00" * (MIN_COMPRESS_SIZE + 200))

    with (
        patch.object(compress, "_classify_elf", return_value=(True, True)),
        patch.object(compress, "_is_already_compressed", return_value=False),
        patch("subprocess.check_call"),
        patch.object(compress, "find_upx", return_value="/usr/bin/upx"),
    ):
        out = compress.compress_tree(tmp_path, level=CompressionLevel.BEST)
    assert set(out) == {f1, f2}


# -------- main CLI integration --------------------------------------------


def test_cli_compress_default_level_is_best() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--compress", "/bin/x"])
    assert args.compress_level is CompressionLevel.BEST


def test_cli_compress_with_explicit_level() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--compress", "--compress-level", "ultra", "/bin/x"])
    assert args.compress_level is CompressionLevel.ULTRA


def test_cli_no_compress_flag_is_none() -> None:
    from dockerize.main import parse_args

    args = parse_args(["/bin/x"])
    assert args.compress_level is None


def test_cli_compress_invalid_level_rejected() -> None:
    from dockerize.main import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--compress", "--compress-level", "bogus", "/bin/x"])


def test_cli_compress_libs_passthrough() -> None:
    from dockerize.main import parse_args

    args = parse_args(["--compress", "--compress-libs", "/bin/x"])
    assert args.compress_libs is True
