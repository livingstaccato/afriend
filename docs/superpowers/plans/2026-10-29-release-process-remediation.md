# Release-process remediation

Goal: close all five findings from the end-to-end process audit without publishing
anything. Keep reviewer CLIs latest by default with explicit optional overrides.

- [x] Require successful complete CI for the exact tagged commit before release
  artifact construction/publication; reject missing, pending, failed, mismatched
  or incomplete job evidence. Preserve main ancestry and protected approval.
- [x] Make package uploads retry-safe: verify existing filename hashes against
  the original run artifacts, stage only missing files, fail on mismatch/network
  uncertainty, and separate canonical/former-name publication jobs. Apply the
  same preparation to TestPyPI. Never blindly skip an existing file.
- [x] Require measured provider-specific parser diagnostics for negative startup
  probes; reject argv-echoing unhandled exceptions and preserve raw evidence.
- [x] Require named real containment cases to pass using structured outcomes,
  rejecting skips, deselection, missing cases and failures despite ambient
  PYTEST_ADDOPTS/plugin changes.
- [x] Run the full mutation probe in hosted Linux CI once, serially after tests.
- [x] Add regressions and local failure-injection coverage, run all portable
  quality checks and workflow validation, obtain independent review, reconcile
  documentation/changelog/version counts, push PR #9 and watch every CI job.

Parallel ownership: containment gate + tests; startup verifier + tests; publish
preparation + tests. Coordinator owns exact-commit CI gate, workflows,
integration, documentation, and real local publication-retry simulations.
No agent or coordinator may publish, tag, merge, change publisher policy or
forward model credentials as part of this remediation.

Local quality passed: 2,913 tests passed,31 skipped; all16 mutation probes killed.
Independent integrated review finding (Node crash) repaired and reverified.
Documentation and changelog reconciled; version remains0.13.0,2,944 collected
tests. Implementation `f153ec7` completed all eight hosted jobs successfully in
run40799404634, including the corrected native Windows suite.
