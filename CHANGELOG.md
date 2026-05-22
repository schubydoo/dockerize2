# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0](https://github.com/schubydoo/dockerize2/compare/v0.4.0...v0.5.0) (2026-05-22)


### Features

* publish a minimal :slim image variant ([#92](https://github.com/schubydoo/dockerize2/issues/92)) ([11cb864](https://github.com/schubydoo/dockerize2/commit/11cb864fa5a084a736a141d0d5ec60717bab753a))


### Build System & Dependencies

* consolidate apt layer so build-only tools don't persist ([#90](https://github.com/schubydoo/dockerize2/issues/90)) ([7f41b2a](https://github.com/schubydoo/dockerize2/commit/7f41b2a78d2521f129ffc075e966f86a103eed09))

## [0.4.0](https://github.com/schubydoo/dockerize2/compare/v0.3.3...v0.4.0) (2026-05-22)

`--output-oci` is now fully daemonless, and the runtime image drops the
docker-buildx plugin — a smaller image that also clears the bundled-binary
CVEs that plugin and the older docker CLI carried.

### Features

* **Native OCI archive writer** ([#87](https://github.com/schubydoo/dockerize2/issues/87)) ([ed91273](https://github.com/schubydoo/dockerize2/commit/ed9127302024193864abb4f15cf5223e4b5657bc)): `--output-oci` assembles the single-layer `FROM scratch` image in pure Python — tar+gzip the staging directory into one layer blob, then write the image config, manifest, `index.json`, and `oci-layout` per the OCI image-layout spec. No daemon, no `buildx`, no `podman`; it works anywhere Python runs. Validated by a `docker load` round-trip and content-addressable digest/diffID checks.

### Changed

* The runtime image no longer bundles the **docker-buildx** plugin — nothing invokes it now that `--output-oci` is native — for a further image-size reduction on top of the v0.3.3 cut.
* The generated `Dockerfile` is now excluded from the image layer; previously `COPY . /` leaked it into the image root.
* Removed the now-dead `dockerize doctor` buildx check and the buildx Renovate custom manager.

### Security

* Bumped the bundled static **docker CLI to 29.5.2** (Go 1.26.3), clearing 8 Go-stdlib CVEs Trivy flagged against the bundled `docker` binary (5 high / 3 medium).
* Dropping docker-buildx also removes the 2 vendored-`docker/docker` CVEs (CVE-2026-34040, CVE-2026-33997) that the bundled buildx binary carried.

## [0.3.3](https://github.com/schubydoo/dockerize2/compare/v0.3.2...v0.3.3) (2026-05-22)

Rolls up the security, container, automation, and documentation hardening
since v0.3.2. This is also the first release published to **production PyPI**.

### Added

* **Release Please** automates version tagging and CHANGELOG maintenance:
  each push to `master` re-evaluates Conventional Commits since the last tag
  and, on a `feat:`/`fix:`/`perf:`, opens a release PR that bumps
  `__version__`, rewrites the CHANGELOG, and updates the manifest. Merging it
  fires `release.yml` (PyPI + GHCR multi-arch image).
* Community health files: a `CODE_OF_CONDUCT.md`, a pull-request template, and
  issue templates (bug report, feature request, and a config routing security
  reports to the private-advisory flow).
* PyPI Trove classifiers for the GPLv3+ license and the CPython implementation.
* An "Acknowledgements" section (README) and "Development assistance" note
  (NOTICE) disclosing AI-assisted development; original-project credit to
  `dockerize` / Lars Kellogg-Stedman is unchanged.
* Inline `Dockerfile` comment documenting why the runtime stage runs as root
  (the `--runtime docker` path needs the host's root-owned socket) and
  pointing socket-averse users to `--output-oci`.

### Changed

* The runtime container image is ~39% smaller (**~754 MB → ~460 MB**): the
  full `docker.io` engine is replaced with the static Docker CLI — dropping
  the unused `dockerd`/`containerd`/`runc` and upgrading the client from
  20.10 to 29.x.
* `--output-oci` now raises an actionable error when the buildx driver cannot
  export an OCI archive (pointing to the containerd image store, a
  `docker-container` builder, or `--runtime podman`) instead of failing
  opaquely.
* Branch protection now requires the Zizmor `workflow audit` and the
  `conventional PR title` checks to pass before a PR can merge.
* Replaced defensive `assert` statements in `Dockerize` with explicit
  `RuntimeError`s via a `_require_targetdir()` helper — `assert` is a no-op
  under `python -O`, so the prior checks could silently bypass.

### Security

* Pull the security-patched `libgnutls30` (`3.7.9-2+deb12u7`) over the pinned
  base image, resolving a batch of GnuTLS CVEs (2 critical, 3 high, 7 medium)
  that the upstream base image had not yet picked up.
* Trivy hard-gates the **filesystem** scan on fixable CVEs in our own
  dependencies; the **image** scan reports to the Security tab (report-only,
  as it covers bundled third-party binaries we usually can't action).
  Severities aligned to `CRITICAL,HIGH,MEDIUM`.
* Enabled ruff's `flake8-bandit` (`S`) rules to catch security anti-patterns
  (hardcoded secrets, unsafe `subprocess`, insecure temp files) at lint time.

### Bug Fixes

* add tool and command context to subprocess failures ([#82](https://github.com/schubydoo/dockerize2/issues/82)) ([f3a9566](https://github.com/schubydoo/dockerize2/commit/f3a9566cf241f837c9f0b8b142afed58985e92bc))

### Documentation

* Refreshed `examples/` for the current CLI and added `jq`, `curl`, `ffmpeg`,
  `sqlite3`, and static-Go examples; replaced the defunct `thttpd` example
  with `mini-httpd`. Corrected the `--output-oci` daemon/socket documentation.

### Continuous Integration

* Pull requests now build the Dockerfile and Trivy-scan the resulting image.
* Releases publish to production PyPI via Trusted Publishing (OIDC), gated by
  a `pypi` environment that restricts deployment to `v*` tags and requires
  maintainer approval.

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
- `--env KEY=VALUE` to bake environment variables into the produced
  image (rendered into the Dockerfile `ENV` block / OCI image config),
  repeatable like `--label`.

## Pre-fork history

See the [upstream repository](https://github.com/larsks/dockerize) for
changes prior to the fork.
