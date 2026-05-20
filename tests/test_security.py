"""Unit tests for ``dockerize.security`` and the security guards in
``dockerize.dockerize``."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dockerize.dockerize import Dockerize
from dockerize.security import is_sensitive_path, loader_env


@pytest.mark.parametrize(
    "path",
    [
        "/etc/shadow",
        "/etc/gshadow",
        "/etc/sudoers",
        "/etc/sudoers.d/whatever",
        "/root/.ssh/id_rsa",
        "/root/.aws/credentials",
        "/root/.docker/config.json",
        "/root/.kube/config",
    ],
)
def test_sensitive_paths_detected(path: str) -> None:
    assert is_sensitive_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/usr/bin/ls",
        "/lib64/libc.so.6",
        "/tmp/somefile",
    ],
)
def test_non_sensitive_paths_allowed(path: str) -> None:
    assert is_sensitive_path(path) is False


def test_user_home_ssh_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home" / "alice"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows
    assert is_sensitive_path(f"{fake_home}/.ssh/id_rsa") is True
    assert is_sensitive_path(f"{fake_home}/code/project.py") is False


def test_loader_env_strips_ld_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/bad")
    env = loader_env()
    assert "LD_PRELOAD" not in env
    assert "LD_LIBRARY_PATH" not in env
    assert env.get("PATH", "").startswith("/usr/bin")


# -------- Dockerize.add_file sensitive-path refusal -----------------------


def test_add_file_refuses_sensitive_by_default() -> None:
    app = Dockerize()
    with pytest.raises(ValueError, match="sensitive host path"):
        app.add_file("/etc/shadow")


def test_add_file_allows_sensitive_with_flag() -> None:
    app = Dockerize(allow_sensitive=True)
    app.add_file("/etc/shadow")
    assert ("/etc/shadow", "/etc/shadow") in app.paths


# -------- Dockerize.add_user / add_group no_host_lookup -------------------


def test_add_user_bare_name_rejected_with_no_host_lookup() -> None:
    app = Dockerize(no_host_lookup=True)
    with pytest.raises(ValueError, match="no-host-lookup"):
        app.add_user("alice")


def test_add_user_colon_form_accepted_with_no_host_lookup() -> None:
    app = Dockerize(no_host_lookup=True)
    app.add_user("alice:x:1000:1000::/:/bin/sh")
    assert app.users == ["alice:x:1000:1000::/:/bin/sh"]


def test_add_group_bare_name_rejected_with_no_host_lookup() -> None:
    app = Dockerize(no_host_lookup=True)
    with pytest.raises(ValueError, match="no-host-lookup"):
        app.add_group("staff")


# -------- runtime resolution via shutil.which -----------------------------


def test_build_image_raises_when_runtime_missing(tmp_path: Path) -> None:
    app = Dockerize(targetdir=str(tmp_path), runtime="never-exists-xyz")
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(FileNotFoundError, match="not found on PATH"),
    ):
        app.build_image()


def test_build_image_resolves_runtime_absolute_path(tmp_path: Path) -> None:
    app = Dockerize(targetdir=str(tmp_path), runtime="docker", tag="x:1")
    with (
        patch("shutil.which", return_value="/usr/local/bin/docker"),
        patch("subprocess.check_call") as run,
    ):
        app.build_image()
    cmd = run.call_args.args[0]
    assert cmd[0] == "/usr/local/bin/docker"


# -------- OCI labels ------------------------------------------------------


def test_oci_labels_contain_required_keys() -> None:
    app = Dockerize(tag="myimg:1")
    labels = app.oci_labels()
    assert labels["org.opencontainers.image.title"] == "myimg:1"
    assert labels["org.opencontainers.image.source"].startswith("https://github.com/")
    assert labels["org.opencontainers.image.licenses"] == "GPL-3.0-or-later"
    assert "org.opencontainers.image.created" in labels


def test_extra_labels_override_defaults() -> None:
    app = Dockerize(extra_labels={"org.opencontainers.image.title": "custom"})
    labels = app.oci_labels()
    assert labels["org.opencontainers.image.title"] == "custom"


def test_dockerfile_contains_label_block(tmp_path: Path) -> None:
    app = Dockerize(targetdir=str(tmp_path), entrypoint="/bin/sh")
    app.generate_dockerfile()
    content = (tmp_path / "Dockerfile").read_text()
    assert "LABEL" in content
    assert 'org.opencontainers.image.licenses="GPL-3.0-or-later"' in content


# -------- nss-modules allowlist -------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX path semantics")
def test_resolve_deps_filters_nss_libs(tmp_path: Path) -> None:
    """resolve_deps should only copy nss libs matching the allowlist."""
    target = tmp_path / "image"
    # Seed target with a fake binary so resolve_deps' os.walk hands at least
    # one path to DepSolver.add (which we then mock to inject our fake dep).
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "fakebin").write_bytes(b"\x7fELF" + b"\x00" * 100)

    libdir = tmp_path / "libdir"
    libdir.mkdir()
    (libdir / "libnss_files.so.2").write_bytes(b"files")
    (libdir / "libnss_systemd.so.2").write_bytes(b"systemd")  # NOT in allowlist
    (libdir / "libresolv.so.2").write_bytes(b"resolv")

    from dockerize.depsolver import DepSolver

    def fake_add(self: DepSolver, path: object) -> None:
        # Pretend the bin needs libnss_files (in this libdir) so prefixes() finds it.
        self.deps.add(str(libdir / "libnss_files.so.2"))

    app = Dockerize(targetdir=str(target), nss_modules=("files",))
    with patch.object(DepSolver, "add", new=fake_add):
        app.resolve_deps()

    copied = target / str(libdir).lstrip("/")
    assert (copied / "libnss_files.so.2").exists()
    assert (copied / "libresolv.so.2").exists()
    assert not (copied / "libnss_systemd.so.2").exists()


# -------- depsolver env sanitization + timeout ----------------------------


def test_depsolver_loader_invocation_uses_sanitized_env() -> None:
    from dockerize import depsolver

    fake_out = "\tlibc.so.6 => /lib/libc.so.6 (0x00007f0000000000)\n"
    with (
        patch.object(depsolver, "_read_interpreter", return_value="/lib/ld.so"),
        patch("subprocess.check_output", return_value=fake_out) as run,
    ):
        d = depsolver.DepSolver()
        d.add(Path(__file__))  # path is a real file
    env_kw = run.call_args.kwargs["env"]
    assert "LD_PRELOAD" not in env_kw
    assert env_kw["PATH"].startswith("/usr/bin")
    assert run.call_args.kwargs["timeout"] == depsolver.LOADER_TIMEOUT_SECONDS
