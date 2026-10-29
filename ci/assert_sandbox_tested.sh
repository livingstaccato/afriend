#!/usr/bin/env bash
# Require real per-node containment PASS evidence, including when ambient pytest
# options deselect tests or a plugin skips them for an unexpected reason.
set -euo pipefail

uv run python -m pytest -p ci.containment_gate \
  tests/test_sandbox.py tests/test_sandbox_findings.py tests/test_scratch_placement.py \
  tests/test_containment_readonly.py -q -rs

echo "containment tests ran."
