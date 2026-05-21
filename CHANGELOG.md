# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New "Acknowledgements" section in `README.md` and a "Development
  assistance" paragraph in `NOTICE` disclose that this fork is
  developed with assistance from Claude (Anthropic) as a
  pair-programming and code-review tool, while the maintainer directs
  all work and retains editorial control over merges. Original-project
  credit to `dockerize` and Lars Kellogg-Stedman is unchanged in
  `NOTICE` and the README fork-context callout.

### Changed
- Branch protection now requires the Zizmor (`workflow audit`) check
  to pass before a PR can merge. Previously Zizmor ran on every PR
  but its result didn't gate merges. `OSSF Scorecard` is intentionally
  not gated — its workflow has no `pull_request:` trigger, so making
  it required would leave every PR perpetually pending.

### Security
- Trivy image scan now fails the workflow on findings (the scan and
  SARIF-upload steps no longer carry `continue-on-error: true`), so a
  `CRITICAL` or `HIGH` CVE in the runtime image stops merges instead
  of passing CI silently.
- Image-scan severity threshold aligned to `CRITICAL,HIGH,MEDIUM` to
  match the filesystem scan; `MEDIUM` findings in the runtime image
  are no longer invisible.
- Enabled ruff's `flake8-bandit` (`S`) rule set so security
  anti-patterns (hardcoded secrets, unsafe `subprocess` usage,
  insecure temp files, jinja2 autoescape) are caught at lint time.
  `S603` is project-wide-ignored because the codebase consistently
  uses list-form `subprocess` argv (`S602` still catches `shell=True`
  regressions). Test-only rules `S101`/`S108` are scoped to
  `tests/*` so pytest's `assert` idiom continues to work.

### Changed
- Replaced all `assert` statements used for defensive runtime
  validation in `Dockerize` with explicit `RuntimeError` raises via
  a new `_require_targetdir()` helper. `assert` is a no-op under
  `python -O`, so the prior checks could silently bypass and surface
  as `AttributeError` later in the build.

## [0.3.2] - 2026-05-20

### Fixed
- Multi-arch release build fails on `linux/arm/v7` because the bare
  `COPY --from=ghcr.io/astral-sh/uv:0.11.15@sha256:...` in the builder
  stage makes BuildKit resolve the uv image's manifest for *every*
  target platform — but uv has no `linux/arm/v7` manifest, so the
  resolve step 404s and the entire build aborts. Wrap the source in a
  `--platform=$BUILDPLATFORM`-pinned named stage (`uv-source`) so
  BuildKit only resolves it once, for the build host. v0.3.1 was
  tagged but did not publish a GHCR image because of this bug;
  v0.3.2 is its drop-in replacement.

### Changed
- `release.yml` TestPyPI publish step now passes `skip-existing: true`,
  so a retry of a partially-failed release run no longer aborts on the
  publish step's duplicate-version check.

## [0.3.1] - 2026-05-20

### Security
- Bumped `docker/buildx` from v0.21.2 to v0.34.1 in the runtime image,
  clearing ~65 known-fixed CVEs across the Go stdlib (1.23.6 → 1.26.x),
  `buildkit`, `containerd`, `grpc`, and `otel` transitive deps that were
  bundled in the v0.3.0 image.
- Bumped `upx` from 5.0.2 to 5.1.1.
- Pinned all Dockerfile base images by manifest-list digest
  (`python:3.14-slim-bookworm`, `golang:1.26-bookworm`,
  `ghcr.io/astral-sh/uv:0.11.15`). Renovate's `docker` manager keeps the
  digests current.

### Changed
- Builder stage now runs on `--platform=$BUILDPLATFORM`. The dockerize
  wheel is `py3-none-any`, so building it three times under QEMU was
  wasted work; the same artefact now ships into every per-arch runtime
  stage. Materially faster multi-arch release builds.
- `uv` for the builder stage now comes from
  `ghcr.io/astral-sh/uv:0.11.15` (digest-pinned) instead of a
  `pip install` line. Satisfies Scorecard's pin-by-hash check and
  removes a network call from each builder run.
- Release workflow now creates a GitHub Release on every `v*` tag with
  the matching `CHANGELOG.md` section as the body and the wheel + sdist
  attached. Uses the preinstalled `gh` CLI (no extra third-party Action
  dependency).
- Renovate now tracks `.pre-commit-config.yaml` hooks and the
  `UPX_VERSION` / `BUILDX_VERSION` / `SYFT_VERSION` `ARG`s in the
  Dockerfile via `customManagers`. `.github/dependabot.yml` removed —
  Renovate is the single dependency manager.
- Branch protection: required PR reviews removed. The fork-PR
  workflow-approval gate already blocks untrusted CI runs, so the
  review requirement was double-locking and slowing maintainer merges
  without adding security.

### Fixed
- GHCR multi-arch image manifest list now carries the
  `org.opencontainers.image.description` annotation
  (`DOCKER_METADATA_ANNOTATIONS_LEVELS: manifest,index`), so the
  GitHub Packages page shows the project description instead of
  "No description provided".
- README: refreshed the fork notice (continuation framing, not "active
  development now happens here") and brought the Synopsis block up to
  date with the current `dockerize --help` output (security options,
  compression, `--sbom`, `--output-oci`, `--label`).

### Internal
- New tests covering `--compress` / `--sbom` / `--output-oci` wiring
  in `Dockerize` (7 unit tests asserting the call paths can't silently
  disconnect).
- New tests for `oci_output` subprocess-failure paths (3 tests pinning
  `buildx` / `podman build` / `podman save` error propagation and call
  ordering).
- New integration tests for `--compress` (UPX magic check) and
  `--sbom` (SPDX JSON validation), Linux-only, opt-in via
  `--run-integration`. CI integration job now installs `upx-ucl` and
  `syft` (pinned to `SYFT_VERSION`).
- CI matrix now enforces `--cov-fail-under=75` so coverage can't
  silently regress.

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
