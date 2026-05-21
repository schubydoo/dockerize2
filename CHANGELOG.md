# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-20

### Added
- Fork groundwork: `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
  `NOTICE`, comprehensive `.gitignore`, fork-status notice in `README.md`.
- PEP 621 packaging via `pyproject.toml` (hatchling backend) + `uv.lock`.
- `[dev]` optional-dependencies group: `pytest`, `pytest-cov`, `ruff`,
  `mypy`, `pre-commit`.
- `ruff` and `mypy --strict` configured; both pass cleanly on the package.
- Type hints throughout `dockerize/`; `argparse` namespace replaced with a
  typed `CliArgs` dataclass via `dockerize.main.parse_args`.
- Static-binary fast path: ELF binaries with no `.interp` section
  (statically linked Go/Rust/musl/busybox-static binaries) skip the
  dynamic-loader step entirely. They are copied as-is.
- Initial pytest suite (`tests/`) covering `depsolver`, `dockerize`, and
  `main`. `@pytest.mark.integration` + `--run-integration` opt-in for the
  Linux-only end-to-end build test. Symlink-dependent tests skip on
  Windows (no elevated permissions assumed).
- **Security hardening**:
  - `--allow-sensitive` flag (default off) and a built-in refusal list
    for known-credential paths (`/etc/shadow`, `~/.ssh/*`, `~/.aws/*`,
    `~/.docker/config.json`, `~/.kube/config`, `~/.netrc`, `~/.gitconfig`).
  - `--no-host-lookup` flag — rejects bare user/group names so the host
    `/etc/passwd` and `/etc/group` cannot leak into the image.
  - `--nss-modules` allowlist (default: `files,dns`) — only matching
    `libnss_<module>*` libs are copied (previously *all* libnss/libresolv
    libs from each dep prefix were copied, e.g. `libnss_systemd`,
    `libnss_winbind`, etc.).
  - Dynamic-loader invocation now runs with a sanitised env (no `LD_*`)
    and a 15-second hard timeout.
  - `shutil.which` resolves `--runtime` to an absolute path; missing
    runtime yields a clear `FileNotFoundError` instead of a confusing
    subprocess failure.
  - `shutil.rmtree` cleanup failures are now logged at `WARNING` instead
    of being silently swallowed.
  - **Dockerfile** template emits OCI `org.opencontainers.image.*`
    labels (`title`, `version`, `source`, `licenses`, `created`).
    Customisable via `--label KEY=VALUE` (repeatable).
- **UPX compression**: `--compress` flag applies UPX to ELF executables
  in the built image. `--compress-level {normal,best,ultra}` (default
  `best`). `--compress-libs` opts in to compressing shared libraries
  (deprecated UPX feature, off by default). Files <50 KB are skipped.
  Already-compressed files are detected via `upx -t` and skipped, so the
  operation is idempotent. Missing `upx` yields a clear, actionable
  error.
- **`--sbom PATH`**: generates a Software Bill of Materials of the build
  context via `syft`. `--sbom-format {spdx-json,cyclonedx-json,syft-json}`
  (default `spdx-json`).
- **`--output-oci PATH`**: emits an OCI image archive to `PATH` without
  pushing into a daemon. Uses `docker buildx` when available; falls back
  to `podman build` + `podman save --format oci-archive`. This is the
  recommended mode when running `dockerize` from inside a container —
  no need to mount `/var/run/docker.sock`.
- **`dockerize doctor`** subcommand checks the host for Python (>=3.11),
  `docker` / `podman`, `upx`, `syft`, and `docker buildx`. Exits 0 when
  a usable build environment is detected, 1 otherwise. Cuts support
  load: a single command tells you what's missing.
- **Multi-arch container image** at `ghcr.io/schubydoo/dockerize2`
  (`linux/amd64`, `linux/arm64`, `linux/arm/v7`). Three-stage build on
  `python:3.14-slim-bookworm`; `syft` cross-compiled from source via a
  `golang:1.26-bookworm` builder stage (anchore doesn't publish armv7
  binaries upstream). Ships `upx 5.x`, `docker buildx`, `syft`, and the
  Docker CLI; ENTRYPOINT is `dockerize`. README documents the
  recommended socket-free `--output-oci` invocation alongside the
  classic socket-mount form.
- **CI / supply-chain workflows** (all in `.github/workflows/`):
  - `ci.yml` — pytest matrix on `{ubuntu, macos, windows}` × `{3.11, 3.12, 3.13}`;
    Linux-only integration job runs the end-to-end build test.
  - `lint.yml` — `ruff check`, `ruff format --check`, `mypy --strict`.
  - `codeql.yml` — weekly CodeQL Python analysis.
  - `zizmor.yml` — workflow static analysis (catches `pull_request_target`
    misuse, script-injection, unpinned actions).
  - `trivy.yml` — repo + image vulnerability scan (SARIF to Code Scanning).
  - `gitleaks.yml` — secret scan on PRs + weekly full-history sweep.
  - `scorecard.yml` — OSSF Scorecard weekly.
  - `release.yml` — on `v*` tag: PyPI Trusted Publishing + multi-arch
    GHCR push (`linux/amd64,linux/arm64,linux/arm/v7`) with provenance,
    SBOM attestation, and cosign keyless signing of every tag.
- **`dependabot.yml`** — GitHub Actions updates only (Python deps go
  through Renovate).
- **`renovate.json`** — `config:recommended` + auto-pin actions to
  digests + lockfile maintenance + patch-only auto-merge for dev tooling
  + vulnerability alerts.
- **`.pre-commit-config.yaml`** — `trailing-whitespace`,
  `end-of-file-fixer`, `check-yaml`, `check-toml`, `ruff` (+`ruff-format`),
  and `gitleaks`.
- **`.github/settings.yml`** — Probot Settings declarative config for
  branch protection (require status checks, linear history, no force
  pushes), allowed merge types, and `delete_branch_on_merge`.

### Removed
- Legacy `setup.py`, `setup.cfg`, `MANIFEST.in`, `requirements.txt`
  (replaced by `pyproject.toml`).
- **Host-tool dependencies removed**:
  - `rsync` is no longer required; `shutil.copytree`/`shutil.copy2`
    handle the copy with equivalent symlink modes.
  - `objdump` is no longer required; `pyelftools` parses the `.interp`
    section directly.

### Changed
- Repository relaunched as the successor to `larsks/dockerize`, which
  has been dormant since 2020. Upstream is preserved as a historical
  remote.
- Minimum Python bumped to **3.11** (testing matrix: 3.11 / 3.12 / 3.13).
- Version bumped to `0.3.0.dev0` to mark the start of the fork's
  development cycle.

## Ideas / Roadmap

Not committed to a release yet; tracked for future consideration.

- `--from-image BASE` to layer on a base image instead of `scratch`.
- Cross-arch `--platform linux/arm64` passthrough with arch-aware
  `.interp` resolution.
- `--squash` post-process / `SOURCE_DATE_EPOCH` reproducible builds.
- Plugin hook system for new file-classifier types.
- `release-please` for auto-generated release notes.

## Pre-fork history

See the [upstream repository](https://github.com/larsks/dockerize) for
changes prior to the fork.
