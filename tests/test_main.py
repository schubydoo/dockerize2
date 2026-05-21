"""Unit tests for ``dockerize.main``."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from dockerize.compress import CompressionLevel
from dockerize.dockerize import DEFAULT_NSS_MODULES, SymlinkOptions
from dockerize.main import FILETOOLS, CliArgs, main, parse_args


def test_parse_args_minimal() -> None:
    args = parse_args(["/bin/ls"])
    assert isinstance(args, CliArgs)
    assert args.paths == ["/bin/ls"]
    assert args.symlinks == SymlinkOptions.COPY_UNSAFE
    assert args.runtime == "docker"
    assert args.buildcmd == "build"
    assert args.no_build is False
    assert args.filetools is False


def test_single_path_sets_entrypoint() -> None:
    args = parse_args(["/usr/sbin/thttpd"])
    assert args.entrypoint == "/usr/sbin/thttpd"


def test_explicit_entrypoint_wins_over_inferred() -> None:
    args = parse_args(["-e", "/bin/sh", "/usr/sbin/thttpd"])
    assert args.entrypoint == "/bin/sh"


def test_multiple_paths_no_implicit_entrypoint() -> None:
    args = parse_args(["/bin/a", "/bin/b"])
    assert args.entrypoint is None


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("preserve", SymlinkOptions.PRESERVE),
        ("copy-unsafe", SymlinkOptions.COPY_UNSAFE),
        ("skip-unsafe", SymlinkOptions.SKIP_UNSAFE),
        ("copy-all", SymlinkOptions.COPY_ALL),
    ],
)
def test_symlinks_modes(flag: str, expected: SymlinkOptions) -> None:
    args = parse_args(["-L", flag, "/bin/x"])
    assert args.symlinks is expected


def test_symlinks_invalid_mode_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["-L", "bogus", "/bin/x"])


def test_add_file_appended() -> None:
    args = parse_args(["-a", "/host/foo", "/img/foo", "/bin/x"])
    assert ("/host/foo", "/img/foo") in args.add_file


def test_user_and_group_repeated() -> None:
    args = parse_args(["-u", "alice", "-u", "bob", "-g", "staff", "/bin/x"])
    assert args.user == ["alice", "bob"]
    assert args.group == ["staff"]


def test_filetools_flag() -> None:
    args = parse_args(["--filetools", "/bin/x"])
    assert args.filetools is True


def test_no_build_flag() -> None:
    args = parse_args(["-n", "/bin/x"])
    assert args.no_build is True


def test_runtime_and_buildcmd_overrides() -> None:
    args = parse_args(["-R", "podman", "-B", "image build", "/bin/x"])
    assert args.runtime == "podman"
    assert args.buildcmd == "image build"


def test_loglevel_default() -> None:
    args = parse_args(["/bin/x"])
    assert args.loglevel == logging.WARN


def test_verbose_sets_info() -> None:
    args = parse_args(["--verbose", "/bin/x"])
    assert args.loglevel == logging.INFO


def test_debug_sets_debug() -> None:
    args = parse_args(["--debug", "/bin/x"])
    assert args.loglevel == logging.DEBUG


# -------- main() orchestration (heavily mocked) ---------------------------


def test_main_wires_args_into_dockerize() -> None:
    fake_app = MagicMock()
    with patch("dockerize.main.Dockerize", return_value=fake_app) as fake_cls:
        main(
            [
                "-t",
                "img:1",
                "-u",
                "alice:x:1:1::/:/bin/sh",
                "-g",
                "staff:x:50:",
                "-n",
                "/bin/ls",
            ]
        )

    kwargs = fake_cls.call_args.kwargs
    assert kwargs["tag"] == "img:1"
    assert kwargs["entrypoint"] == "/bin/ls"
    # --no-build flips `build` to False
    assert kwargs["build"] is False

    # The CLI -> Dockerize side effects happen on the instance
    fake_app.add_file.assert_any_call("/bin/ls")
    fake_app.add_user.assert_called_once_with("alice:x:1:1::/:/bin/sh")
    fake_app.add_group.assert_called_once_with("staff:x:50:")
    fake_app.build.assert_called_once_with()


def test_main_filetools_resolves_via_which(monkeypatch: pytest.MonkeyPatch) -> None:
    # Resolve every tool name to a deterministic absolute path so the test is
    # platform-independent (real `which("ls")` is None on Windows).
    monkeypatch.setattr("dockerize.main.shutil.which", lambda name: f"/resolved/{name}")
    fake_app = MagicMock()
    with patch("dockerize.main.Dockerize", return_value=fake_app):
        main(["--filetools", "/bin/x"])

    added = {call.args[0] for call in fake_app.add_file.call_args_list}
    assert "/bin/x" in added
    for name in FILETOOLS:
        assert f"/resolved/{name}" in added


def test_main_filetools_skips_tools_not_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When a tool can't be resolved, it's skipped (with a warning), not added.
    monkeypatch.setattr("dockerize.main.shutil.which", lambda name: None)
    fake_app = MagicMock()
    with patch("dockerize.main.Dockerize", return_value=fake_app):
        main(["--filetools", "/bin/x"])

    added = {call.args[0] for call in fake_app.add_file.call_args_list}
    assert added == {"/bin/x"}


def test_main_add_file_pair_forwarded() -> None:
    fake_app = MagicMock()
    with patch("dockerize.main.Dockerize", return_value=fake_app):
        main(["-a", "/host/foo", "/img/foo", "/bin/x"])
    fake_app.add_file.assert_any_call("/host/foo", "/img/foo")


# -------- --label parsing -------------------------------------------------


def test_label_single_parsed() -> None:
    args = parse_args(["--label", "maintainer=schuby", "/bin/x"])
    assert args.extra_labels == {"maintainer": "schuby"}


def test_label_repeated_accumulates() -> None:
    args = parse_args(
        ["--label", "a=1", "--label", "b=2", "/bin/x"],
    )
    assert args.extra_labels == {"a": "1", "b": "2"}


def test_label_value_may_contain_equals() -> None:
    # Only the first '=' splits key from value.
    args = parse_args(["--label", "url=https://x/y?a=b", "/bin/x"])
    assert args.extra_labels == {"url": "https://x/y?a=b"}


def test_label_key_whitespace_stripped() -> None:
    args = parse_args(["--label", "  org.title  =hello", "/bin/x"])
    assert args.extra_labels == {"org.title": "hello"}


def test_label_missing_equals_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--label", "noequalshere", "/bin/x"])


# -------- --nss-modules parsing -------------------------------------------


def test_nss_modules_default() -> None:
    args = parse_args(["/bin/x"])
    assert args.nss_modules == DEFAULT_NSS_MODULES


def test_nss_modules_custom() -> None:
    args = parse_args(["--nss-modules", "files,dns,myhostname", "/bin/x"])
    assert args.nss_modules == ("files", "dns", "myhostname")


def test_nss_modules_strips_whitespace_and_drops_empties() -> None:
    args = parse_args(["--nss-modules", " files , dns ,,", "/bin/x"])
    assert args.nss_modules == ("files", "dns")


# -------- --compress / --compress-level -----------------------------------


def test_compress_defaults_to_best_level() -> None:
    args = parse_args(["--compress", "/bin/x"])
    assert args.compress_level is CompressionLevel.BEST


def test_compress_level_explicit() -> None:
    args = parse_args(["--compress", "--compress-level", "ultra", "/bin/x"])
    assert args.compress_level is CompressionLevel.ULTRA


def test_compress_level_ignored_without_compress() -> None:
    # --compress-level without --compress leaves compression disabled.
    args = parse_args(["--compress-level", "ultra", "/bin/x"])
    assert args.compress_level is None


def test_compress_level_invalid_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--compress", "--compress-level", "bogus", "/bin/x"])


def test_compress_libs_flag() -> None:
    args = parse_args(["--compress", "--compress-libs", "/bin/x"])
    assert args.compress_libs is True


def test_compress_libs_default_false() -> None:
    args = parse_args(["/bin/x"])
    assert args.compress_libs is False
