# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Fork groundwork: `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
  `NOTICE`, comprehensive `.gitignore`, fork-status notice in `README.md`.

### Changed
- Repository relaunched as the successor to `larsks/dockerize`, which
  has been dormant since 2020. Upstream is preserved as a historical
  remote.

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
