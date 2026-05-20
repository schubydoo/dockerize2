"""Unit tests for ``dockerize.doctor`` and the ``doctor`` subcommand."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dockerize import doctor
from dockerize.doctor import (
    CheckResult,
    check_buildx,
    check_python,
    check_tool,
    collect_checks,
    format_report,
    overall_status,
    run,
)


def test_check_python_current() -> None:
    """Whatever Python is running this test must satisfy the floor."""
    result = check_python()
    assert result.is_ok
    assert "." in result.detail


def test_check_python_too_old() -> None:
    with patch.object(doctor, "MIN_PYTHON", (99, 0)):
        result = check_python()
    assert result.status == "missing"


def test_check_tool_missing() -> None:
    with patch("shutil.which", return_value=None):
        r = check_tool("nonesuch")
    assert r.status == "missing"


def test_check_tool_present() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/fakecmd"),
        patch("subprocess.check_output", return_value="fakecmd 1.2.3\n"),
    ):
        r = check_tool("fakecmd")
    assert r.is_ok
    assert "/usr/bin/fakecmd" in r.detail
    assert "fakecmd 1.2.3" in r.detail
    assert "-" in r.detail


def test_check_tool_present_but_version_fails() -> None:
    """When --version fails we still report ok (the binary exists)."""
    with (
        patch("shutil.which", return_value="/usr/bin/fakecmd"),
        patch("subprocess.check_output", side_effect=OSError("boom")),
    ):
        r = check_tool("fakecmd")
    assert r.is_ok


def test_check_buildx_no_docker() -> None:
    with patch("shutil.which", return_value=None):
        r = check_buildx()
    assert r.status == "missing"


def test_check_buildx_available() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.check_call") as run,
    ):
        r = check_buildx()
    run.assert_called_once()
    assert r.is_ok


def test_check_buildx_unavailable() -> None:
    import subprocess

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.check_call", side_effect=subprocess.CalledProcessError(1, "x")),
    ):
        r = check_buildx()
    assert r.status == "warn"


def test_overall_status_no_runtime() -> None:
    results = [
        CheckResult("python", "ok", "3.13.0"),
        CheckResult("docker", "missing"),
        CheckResult("podman", "missing"),
        CheckResult("upx", "missing"),
        CheckResult("syft", "missing"),
        CheckResult("docker buildx", "missing"),
    ]
    assert overall_status(results) == 1


def test_overall_status_ok_with_podman() -> None:
    results = [
        CheckResult("python", "ok", "3.13.0"),
        CheckResult("docker", "missing"),
        CheckResult("podman", "ok", "/usr/bin/podman"),
        CheckResult("upx", "missing"),
        CheckResult("syft", "missing"),
        CheckResult("docker buildx", "missing"),
    ]
    assert overall_status(results) == 0


def test_format_report_contains_marker_per_check() -> None:
    results = [
        CheckResult("python", "ok", "3.13.0"),
        CheckResult("docker", "missing", "not on PATH"),
    ]
    report = format_report(results)
    assert "[ OK ] python" in report
    assert "[FAIL] docker" in report
    assert "not on PATH" in report


def test_run_returns_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    fake = [
        CheckResult("python", "ok", "3.13.0"),
        CheckResult("docker", "missing"),
        CheckResult("podman", "missing"),
        CheckResult("upx", "missing"),
        CheckResult("syft", "missing"),
        CheckResult("docker buildx", "missing"),
    ]
    with patch.object(doctor, "collect_checks", return_value=fake):
        code = run()
    captured = capsys.readouterr()
    assert code == 1
    assert "dockerize doctor" in captured.out
    assert "FAIL" in captured.err


def test_run_returns_zero_when_healthy(capsys: pytest.CaptureFixture[str]) -> None:
    fake = [
        CheckResult("python", "ok", "3.13.0"),
        CheckResult("docker", "ok", "/usr/bin/docker"),
        CheckResult("podman", "missing"),
        CheckResult("upx", "ok"),
        CheckResult("syft", "ok"),
        CheckResult("docker buildx", "ok"),
    ]
    with patch.object(doctor, "collect_checks", return_value=fake):
        code = run()
    captured = capsys.readouterr()
    assert code == 0
    assert "FAIL" not in captured.err


def test_collect_checks_returns_all_expected_names() -> None:
    names = {r.name for r in collect_checks()}
    assert {"python", "docker", "podman", "upx", "syft", "docker buildx"} <= names


def test_main_doctor_subcommand_dispatches() -> None:
    """``dockerize doctor`` should call doctor.run() and exit with its code."""
    from dockerize.main import main

    with (
        patch("dockerize.doctor.run", return_value=0) as fake_run,
        pytest.raises(SystemExit) as exc,
    ):
        main(["doctor"])
    fake_run.assert_called_once()
    assert exc.value.code == 0


def test_main_doctor_failure_returns_one() -> None:
    from dockerize.main import main

    with (
        patch("dockerize.doctor.run", return_value=1),
        pytest.raises(SystemExit) as exc,
    ):
        main(["doctor"])
    assert exc.value.code == 1
