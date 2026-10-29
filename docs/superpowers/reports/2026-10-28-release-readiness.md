# afriend 0.13.0 release audit

Updated on 2026-10-29 UTC (2026-10-28 Pacific). This record supersedes earlier
readiness wording. The runtime and release-process implementation is verified
through `f153ec7`; documentation head `5234def` also passed all eight CI jobs.
**Status: final CI and live-review disposition pending; this is not release clearance.**

The current live-follow-up candidate passed isolated `make quality`: **2,948
passed, 36 skipped**, one existing warning; **16 mutants killed**, zero
survivors/skips. It collects **2,984 tests**. Native Windows CI and the revised
live cross-examination are still pending.
PR #9 remains draft. No merge, production PyPI publication or release tag has
been made. TestPyPI publication and recovery have now been exercised successfully.

## Verification evidence

| Check | Result | Source |
| --- | --- | --- |
| Local `make quality` at corrected implementation | 2,913 passed, 31 skipped, one existing warning; 16 mutants killed, zero survivors/skips | `/tmp/afriend-process-crlf-quality.log` |
| Linux Python 3.11/3.12/3.13 | Each 2,911 passed, 33 skipped | [Implementation CI](https://github.com/livingstaccato/afriend/actions/runs/40799404634) |
| Native Windows suite | 2,803 passed, 141 skipped | Same implementation CI |
| Final prior documentation head | All eight jobs passed at `5234def` | [CI run 40799953672](https://github.com/livingstaccato/afriend/actions/runs/40799953672) |
| Targeted hosted mutation probe | 16 killed, zero survivors/skips on Python 3.13 | Implementation CI |
| Real Linux confinement | Five required node IDs passed setup/call/teardown; skip/deselection fault injections were correctly rejected | Implementation CI; [process review](2026-10-29-release-process-review.md) |
| TestPyPI/OIDC publication | All three projects and six files published at `0.13.0` | [Rehearsal](https://github.com/livingstaccato/afriend/actions/runs/40801742187/attempts/1) |
| Actual publication retry | Three hash checks passed; three upload steps skipped; original artifacts retained | [Retry](https://github.com/livingstaccato/afriend/actions/runs/40801742187/attempts/2) |
| Remote files and isolated installation | All six downloaded files match original bytes; all three packages install and start with correct metadata | [Live verification and durable hashes](2026-10-29-live-testpypi.md) |

Earlier local/Linux runs differed by two historical friend-eval provenance cases in
`tests/test_friend_eval.py`: `test_the_artifact_is_rebuilt_from_git_with_its_recorded_digest`
and `test_an_artifact_that_no_longer_matches_its_digest_is_refused`. They require
a historical spec commit absent from the earlier shallow CI checkout. The new
quality jobs fetch full history, and Python 3.13 requires both named cases to
pass a two-case JUnit check with no skips/failures/errors. Their earlier local
results were not
the new containment, mutation or publication-recovery checks.
Platform-specific skips remain visible; a green suite does not mean zero skips.
The earlier `f153ec7` implementation collected 2,944 tests; the current candidate
collects 2,984. The targeted 16-mutant set covers `envelopes`, `adapters`,
`failures`, `rounds`, `models` and `judgebatch`, not the whole repository.
Current local evidence is retained as a [compressed log](2026-10-29-portable-quality.log.gz)
and [source-hash manifest](2026-10-29-portable-quality.json).

Static lint/formatting, strict source typing, source-length, plugin/version sync,
all six diagram renders, wheel assets/imports and isolated six-distribution
checks passed in `make quality`. Runtime architecture sources and committed
PNG/SVG/digests describe the implementation; process-only fixes do not change
those runtime diagrams.

## Real Windows startup scope

All four real installed npm CLI jobs passed, selecting `latest` without an
override. Captured implementation-run versions were Claude 2.1.312, Codex
0.165.0, OpenCode 2.2.0 and Pi 1.4.0. Every version/help probe exited 0; deliberate
invalid values exited 1 or 2 with the provider-specific parser diagnostic.
No probe timed out or reported suspected orphans. Startup captures are retained
as four `windows-startup-*` workflow artifacts. The quoting repair for native
npm launchers preserves inline JSON, custom profiles and arguments.

Versions are observations, not pins. The four documented `AF_STARTUP_*_VERSION`
repository variables remain optional overrides. These jobs establish native
startup/rejection behavior without model credentials; they do not establish
all providers' authenticated review behavior, AGY startup, Ollama availability,
or a new macOS run.

## Release process and documentation

All five process findings are remediated; the [process review](2026-10-29-release-process-review.md)
records their original evidence, fixes and independent follow-up. Production
release builds and approved publishing jobs require successful exact-commit
push-to-main CI. Publication retries verify original artifact hashes and stage
only missing files. Canonical and aliases have separate jobs. The
[release procedure](../../release-process.md) explains approvals and recovery.

`CHANGELOG.md` covers the integration and enforcement changes. Version 0.13.0
is synchronized across package/plugin/marketplace metadata and both aliases;
each alias requires exactly `afriend==0.13.0`. TestPyPI's published bytes belong
to `5234def`; later skill/documentation edits are not claimed as already uploaded.
The live TestPyPI record includes six durable SHA256 digests and verifies an
installation outside the checkout. Production PyPI's separate publisher
identities and approval environment are not proven by TestPyPI acceptance.

## Live cross-examination and remaining limits

The original requested five-friend run failed to obtain five usable critiques.
A fresh attempt confirmed Claude's individual account spend limit. The user
approved a fresh Codex security worker as its replacement; the superseded run
was cancelled gracefully and preserved. Pi/GLM then timed out during critique and returned invalid judging output.
The user approved a fresh Codex reliability worker using the testability lens as its
replacement. The new roster had Codex security, Codex operations, a separate
Codex reliability/testability worker, OpenCode Kimi and Pi Kimi. It completed
three rounds and all five critiques, with 13 of 15 usable responses. One Pi
judging timeout and one Codex model-capacity refusal left the result incomplete.
The [retained ledger and dispositions](2026-10-29-cross-examination.md) give exact
bounds, states, failures and host treatments. A retry versus retaining the
inconclusive result is awaiting the user's choice; it is not waived.

Documented Windows limitations remain: no OS filesystem confinement, inherited
run-directory ACLs, weaker filesystem-race protection and explicit unsandboxed
opt-in for affected providers. Startup checks do not resolve those boundaries.
No claim of absolute correctness or authorization to publish follows from this
report. Production release remains a separate integration/publication action.

The five mandatory containment cases are:

```text
tests/test_sandbox.py::test_a_file_inside_the_workdir_is_readable
tests/test_sandbox.py::test_a_file_outside_the_workdir_is_not_readable
tests/test_sandbox_findings.py::test_a_confined_process_really_cannot_see_withheld_secrets
tests/test_scratch_placement.py::test_the_reviewed_worktree_is_left_clean
tests/test_containment_readonly.py::test_a_readonly_worktree_allows_reads_and_denies_writes
```

The optional version overrides are `AF_STARTUP_CLAUDE_VERSION`,
`AF_STARTUP_CODEX_VERSION`, `AF_STARTUP_OPENCODE_VERSION` and
`AF_STARTUP_PI_VERSION`. Captured startup results are time-bound observations;
rerun checks before a delayed release or after a harness changes.
