"""Defensive guards: sensitive-path detection, sanitised loader env."""

from __future__ import annotations

import fnmatch
from pathlib import Path

__all__ = ["SENSITIVE_PATTERNS", "is_sensitive_path", "loader_env"]

# Files that almost never belong in a dockerize-produced image. We reject these
# unless the caller passes ``--allow-sensitive``.
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/sudoers",
    "/etc/sudoers.d/*",
    "/root/.ssh/*",
    "/root/.aws/*",
    "/root/.docker/config.json",
    "/root/.kube/config",
    "/root/.netrc",
)


def _expand_home_patterns() -> tuple[str, ...]:
    """Expand ``~`` to the current user's home in a few well-known patterns."""
    home = str(Path("~").expanduser())
    if home == "~":
        return ()
    # On Windows, normalise to forward slashes so fnmatch is consistent.
    home = home.replace("\\", "/")
    return (
        f"{home}/.ssh/*",
        f"{home}/.aws/*",
        f"{home}/.docker/config.json",
        f"{home}/.kube/config",
        f"{home}/.netrc",
        f"{home}/.gitconfig",
    )


def is_sensitive_path(path: str | Path) -> bool:
    """Return ``True`` if ``path`` matches any known sensitive pattern."""
    s = str(Path(path).absolute()) if Path(path).is_absolute() else str(path)
    s = s.replace("\\", "/")  # normalise for Windows-form input
    for pattern in (*SENSITIVE_PATTERNS, *_expand_home_patterns()):
        if fnmatch.fnmatch(s, pattern):
            return True
    return False


def loader_env() -> dict[str, str]:
    """Return a minimal environment for invoking a dynamic loader.

    Strips every ``LD_*`` variable from the parent env so that a malicious
    ``LD_PRELOAD`` in the build host cannot influence the loader invocation,
    and pins ``PATH`` to a short safe value.
    """
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C",
        "LC_ALL": "C",
    }
