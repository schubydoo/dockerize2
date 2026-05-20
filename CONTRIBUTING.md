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

- Branch from `master`; open the PR back against `master`.
- One PR = one logical change. Keep diffs focused and reviewable.
- Commit messages: imperative subject ≤72 chars (`add foo`, `fix bar`),
  body only if context is needed. **Signed commits required** (GitHub
  must show "Verified"). SSH or GPG signing both work — see
  [GitHub's docs](https://docs.github.com/en/authentication/managing-commit-signature-verification).
- Run `uv run ruff check && uv run ruff format --check && uv run mypy &&
  uv run pytest` before pushing.
- Pre-commit hooks are configured in `.pre-commit-config.yaml`. Install
  with `uv run pre-commit install`.

## What we look for

- Tests for new behaviour. Coverage target is ≥85 % on `dockerize/`.
- Type hints on new code (we run `mypy --strict`).
- No new host-tool dependencies. Prefer stdlib + `pyelftools`.
- Documentation updated when CLI flags or behaviour change.

## Renovate / Dependabot

Dependency updates are automated. Renovate (Python deps + lockfile) and
Dependabot (GitHub Actions) open PRs as needed. Patch-level dev-dep
updates auto-merge; everything else needs human review.

## Reporting bugs

Use [GitHub Issues](https://github.com/schubydoo/dockerize2/issues).
Security issues go through Security Advisories — see
[SECURITY.md](SECURITY.md).
