# Contributing

Thanks for your interest in `dockerize2`.

## Quick start

```bash
git clone https://github.com/schubydoo/dockerize2
cd dockerize2
uv sync --all-extras
uv run pytest
```

## Pull-request expectations

- Branch from `master`; open the PR back against `master`. No stacking
  — use GitHub's "Update branch" button to rebase open PRs after a
  sibling merges.
- One PR = one logical change. Keep diffs focused and reviewable.
- **Conventional Commits for the squash-merge subject** (see
  [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)).
  Release Please reads these to bump the version and write the
  CHANGELOG. The merge-commit subject is what counts; individual
  commits on the branch are flattened into it.
- Commit messages: imperative subject ≤72 chars
  (`feat(compress): ...`, `fix(depsolver): ...`), body only if context
  is needed. **Signed commits required** (GitHub must show "Verified").
  SSH or GPG signing both work — see
  [GitHub's docs](https://docs.github.com/en/authentication/managing-commit-signature-verification).
- Run `uv run ruff check && uv run ruff format --check && uv run mypy &&
  uv run pytest` before pushing.
- Pre-commit hooks are configured in `.pre-commit-config.yaml`. Install
  with `uv run pre-commit install`.

### Conventional Commits prefixes

| Prefix | Section in CHANGELOG | Triggers release? |
|---|---|---|
| `feat:` | Features | minor bump |
| `fix:` | Bug Fixes | patch bump |
| `perf:` | Performance | patch bump |
| `feat!:` or `BREAKING CHANGE:` body | Features (breaking) | major bump |
| `docs:` | Documentation | no |
| `test:` | Tests | no |
| `refactor:` | Refactoring | no |
| `build:` | Build System | no |
| `ci:` | Continuous Integration | no |
| `chore:` | Miscellaneous | no |

Optional scopes in parens (`feat(sbom): …`) are encouraged for clarity.

## Releases

Releases are automated by
[Release Please](https://github.com/googleapis/release-please-action).
Each push to `master` re-evaluates the open commits; if there's at
least one `feat:`, `fix:`, or `perf:` since the last tag, Release
Please opens (or updates) a **release PR** that bumps `__version__`
in `dockerize/__init__.py`, updates `CHANGELOG.md`, and edits
`.release-please-manifest.json`. Merging that PR tags the commit
(e.g. `v0.3.3`) and fires the existing `release.yml` workflow to
publish to PyPI and push the multi-arch GHCR image.

Practical implications:

- Don't edit `CHANGELOG.md` by hand for routine PRs — Release Please
  rewrites it from commit messages.
- Don't bump `__version__` by hand — Release Please owns it.
- Pure `docs:`, `ci:`, `chore:` work won't trigger a release on its
  own; it rides along with the next `feat:`/`fix:` commit.

## CI / GitHub Actions

The CI surface lives in `.github/workflows/`. Two big workflows + a few specialised ones:

| File | Purpose | Triggers |
|---|---|---|
| `ci.yml` | Plan + unit tests (matrix) + integration + slim-smoke + aggregator | push to master, pull_request |
| `security.yml` | CodeQL + Gitleaks + Trivy fs/image + Zizmor + dependency-review + aggregator | push, pull_request, weekly cron |
| `lint.yml` | ruff check + ruff format --check + mypy --strict | push, pull_request |
| `pr-title.yml` | Conventional Commits validation on the PR title | pull_request |
| `release-please.yml`, `release.yml`, `scorecard.yml` | release plumbing + supply-chain scoring | tag push / master push / schedule |

### The `plan` job (ci.yml)

The first job in `ci.yml` is `plan`. It diffs the PR against base and emits outputs that gate every other job and shape the test matrix. Most PRs run a **single** matrix cell (`ubuntu-latest × Python 3.13`); master push runs the full 3 OS × 3 Python matrix.

**PR labels:**

| Label | Effect |
|---|---|
| `test:full` | Expand the matrix back to 3 OS × 3 Python on this PR (use for cross-platform-sensitive changes) |
| `test:skip` | Skip `tests` + `integration` + `slim-smoke` entirely (use only for CI plumbing that doesn't change the test surface) |

`security.yml` has a parallel `changes` job that gates trivy-fs / trivy-image / zizmor on file changes (CodeQL, Gitleaks, and dependency-review always run on every PR).

### Branch protection

Only **three** status checks are required:

1. `ci required checks passed` — aggregator that fails iff any `ci.yml` job failed (skipped is fine).
2. `security required checks passed` — same pattern for `security.yml`.
3. `conventional PR title` — validates the PR title parses as Conventional Commits.

Adding a new job: append its ID to the matching aggregator's `needs:` list. Branch protection never needs to change.

## What we look for

- Tests for new behaviour. Coverage target is ≥85 % on `dockerize/`.
- Type hints on new code (we run `mypy --strict`).
- No new host-tool dependencies. Prefer stdlib + `pyelftools`.
- Documentation updated when CLI flags or behaviour change.

## Renovate / Dependabot

Dependency updates are automated. Renovate (Python deps + lockfile) and
Dependabot (GitHub Actions) open PRs as needed. Patch-level dev-dep
updates auto-merge; everything else needs human review.

### One-time GitHub App installs (maintainers only)

Two GitHub Apps drive the automation. Install them once on the repo:

1. **[Renovate](https://github.com/apps/renovate)** — reads
   [`renovate.json`](renovate.json). Opens dependency PRs.
2. **[Settings](https://github.com/apps/settings)** — reads
   [`.github/settings.yml`](.github/settings.yml). Version-controls
   branch protection, allowed merge types, and label set.

PyPI publishing uses [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
— configure the publisher once on PyPI side; no token to manage.

## Reporting bugs

Use [GitHub Issues](https://github.com/schubydoo/dockerize2/issues).
Security issues go through Security Advisories — see
[SECURITY.md](SECURITY.md).
