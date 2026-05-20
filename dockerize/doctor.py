"""``dockerize doctor`` — diagnose host tooling.

Exits 0 when a usable build environment is detected, 1 otherwise. Designed to
cut support load: a one-liner the user can run to find out what's missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from io import StringIO

MIN_PYTHON = (3, 11)


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" / "missing" / "warn"
    detail: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"

    @property
    def marker(self) -> str:
        # ASCII markers — Windows consoles default to cp1252 and choke on
        # box-drawing glyphs.
        return {"ok": "[ OK ]", "warn": "[WARN]", "missing": "[FAIL]"}.get(self.status, "[????]")


def check_python() -> CheckResult:
    ver = sys.version_info
    label = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) >= MIN_PYTHON:
        return CheckResult("python", "ok", label)
    return CheckResult("python", "missing", f"{label} (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")


def check_tool(name: str, version_flag: str = "--version") -> CheckResult:
    """Look up ``name`` on PATH and capture its first-line version output."""
    path = shutil.which(name)
    if path is None:
        return CheckResult(name, "missing", "not on PATH")
    try:
        out = subprocess.check_output(
            [path, version_flag],
            text=True,
            timeout=5,
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return CheckResult(name, "ok", path)
    first = out.splitlines()[0] if out.splitlines() else ""
    return CheckResult(name, "ok", f"{path} - {first}")


def check_buildx() -> CheckResult:
    docker_path = shutil.which("docker")
    if docker_path is None:
        return CheckResult("docker buildx", "missing", "docker not on PATH")
    try:
        subprocess.check_call(
            [docker_path, "buildx", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return CheckResult("docker buildx", "warn", "not available")
    return CheckResult("docker buildx", "ok", "available")


def collect_checks() -> list[CheckResult]:
    """Return the standard set of doctor checks."""
    return [
        check_python(),
        check_tool("docker"),
        check_tool("podman"),
        check_tool("upx"),
        check_tool("syft"),
        check_buildx(),
    ]


def format_report(results: list[CheckResult]) -> str:
    """Pretty-print check results into a single report string."""
    width = max(len(r.name) for r in results)
    out = StringIO()
    out.write("dockerize doctor - host readiness check\n\n")
    for r in results:
        out.write(f"  {r.marker} {r.name.ljust(width)}  {r.detail}\n")
    return out.getvalue()


def overall_status(results: list[CheckResult]) -> int:
    """Return 0 if a usable build env is detected, else 1."""
    by_name = {r.name: r for r in results}

    if not by_name["python"].is_ok:
        return 1

    # At least one container runtime is required to actually build.
    if not (by_name["docker"].is_ok or by_name["podman"].is_ok):
        return 1

    return 0


def run() -> int:
    """Entry point used by the ``doctor`` subcommand. Returns the exit code."""
    results = collect_checks()
    print(format_report(results), end="")
    code = overall_status(results)
    if code != 0:
        print(
            "\nFAIL: missing prerequisites for a successful build "
            "(need Python >= 3.11 and at least one container runtime).",
            file=sys.stderr,
        )
    return code
