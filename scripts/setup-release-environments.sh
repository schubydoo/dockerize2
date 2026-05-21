#!/usr/bin/env bash
# Create the two release environments used by .github/workflows/release.yml.
#
# - testpypi: no human gate, restricted to v* tags. Used right now.
# - pypi:     manual approval required (maintainer = required reviewer),
#             restricted to v* tags. Wired up but unused until release.yml
#             is flipped from TestPyPI to PyPI.
#
# Idempotent. Safe to re-run. Requires `gh` authed as a repo admin.

set -euo pipefail

REPO="${REPO:-schubydoo/dockerize2}"
MAINTAINER_ID="${MAINTAINER_ID:-12485317}"  # schubydoo

create_env() {
  local name="$1"
  local reviewers_json="$2"  # e.g. '[]' or '[{"type":"User","id":12485317}]'

  echo "==> environment: ${name}"
  gh api -X PUT "repos/${REPO}/environments/${name}" \
    --input - >/dev/null <<JSON
{
  "wait_timer": 0,
  "prevent_self_review": false,
  "reviewers": ${reviewers_json},
  "deployment_branch_policy": {
    "protected_branches": false,
    "custom_branch_policies": true
  }
}
JSON

  # Branch/tag policies must be added separately. Wipe any existing
  # policies first so re-runs don't accumulate duplicates.
  local existing
  existing=$(gh api "repos/${REPO}/environments/${name}/deployment-branch-policies" --jq '.branch_policies[].id' 2>/dev/null || true)
  for id in ${existing}; do
    gh api -X DELETE "repos/${REPO}/environments/${name}/deployment-branch-policies/${id}" >/dev/null
  done

  gh api -X POST "repos/${REPO}/environments/${name}/deployment-branch-policies" \
    --input - >/dev/null <<'JSON'
{"name": "v*", "type": "tag"}
JSON
}

create_env "testpypi" "[]"
create_env "pypi"     "[{\"type\":\"User\",\"id\":${MAINTAINER_ID}}]"

echo
echo "Done. Next manual steps:"
echo "  1. Register a pending Trusted Publisher on https://test.pypi.org"
echo "     - Project: dockerize2"
echo "     - Owner:   schubydoo"
echo "     - Repo:    dockerize2"
echo "     - Workflow: release.yml"
echo "     - Environment: testpypi"
echo
echo "  2. (Optional, for when you're ready to flip to prod) register the same"
echo "     pending publisher on https://pypi.org with environment 'pypi'."
