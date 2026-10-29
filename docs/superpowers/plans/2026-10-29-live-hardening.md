# Live-release follow-up

The user requested all remaining release-verification gaps addressed and approved
replacing exhausted Claude with a fresh Codex security worker.

- [x] Publish six distributions to TestPyPI using existing OIDC environments;
  verify remote bytes, isolated install, and a completed-upload retry.
- [x] Document explicit failed-friend recovery in canonical skill and synced
  plugin; verify baseline gaps and replacement/quota/authority scenarios.
- [x] Repair the independently confirmed Windows npm Node CWD lookup exposure;
  exercise a real unsafe control and hardened inventory/readiness on Windows.
- [x] Require complete measured startup diagnostics and bind release-gate names
  to explicit workflow job names/matrices/steps; add meaningful regressions.
- [ ] Triage all live findings, finish five usable critiques and three-round
  cross-examination, rerun portable quality and hosted checks, reconcile evidence.

Preserve failed/interrupted runs and distinguish TestPyPI from production PyPI.
No production tag, merge, billing/login change or publisher-policy change is
part of this work. Child-process source mutations must not overlap live reviews.

Portable quality now passes at 2,948 tests passed / 36 skipped, 16 mutants killed.
The latest-default Codex eval image actually built and passed startup/rejection
probes at 0.165.0; optional version configuration and no-cache refresh are tested.
All five approved workers returned usable critiques across a three-round attempt.
Two judging failures left the live result incomplete. Native Windows proof
and all eight hosted checks passed at `b707327`; final live-review disposition
remains required.
