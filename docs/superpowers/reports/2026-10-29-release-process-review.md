# Remediation disposition

The review below records the original findings at `75ba1f8`; its open-finding
status and statement that no changes were made describe that review only.
The current candidate implements all five fixes. Integrated `make quality` passed: **2,909 passed, 31 skipped**, one existing
warning; all16 mutants killed, zero survivors/skips. Static, diagram, wheel and
isolated six-distribution checks passed. Hosted CI is pending.

| Finding | Implemented remediation | Regression evidence |
| --- | --- | --- |
| Exact commit CI | API gate before build and after publisher approval | Missing, pending, failed, wrong identity and skipped-step cases |
| Interrupted uploads | Separate jobs; SHA256 verification and missing-file staging | Real Twine loopback partial sdist and alias retries; forged hash rejection |
| Startup crash false green | Provider-specific diagnostic patterns and traceback rejection | Captured four-provider diagnostics and real argv-echo crash |
| Containment false green | Five named real tests must pass setup, call and teardown | Skipped, deselected, missing and xfailed cases rejected |
| Hosted mutation omission | Full probe serialized after pytest on Python 3.13 | Workflow wiring and complete probe during quality |

Independent integrated review identified an additional Node-stack variant of
the startup false green. Four new regressions failed before the repair and pass
after it; the reviewer reran the actual Node exception and confirmed rejection.
All four captured valid provider diagnostics remain accepted. The real sandbox
gate passed; actual all-skipped and deselected fault injections now exit1.
Read-only GitHub verification rejected this PR commit because it has no main
push run. Evidence: `/tmp/afriend-process-remediation-quality.log`,
`/tmp/afriend-process-real-containment.log`,
`/tmp/afriend-process-all-skipped-rejected.log`, and
`/tmp/afriend-process-deselected.log`.

Actual OIDC acceptance, public/TestPyPI uploads and authenticated provider reviews
remain outside these checks. Runtime architecture diagrams are unchanged because
these fixes affect CI and release orchestration.

---

# End-to-end adversarial release-process review

## Executive assessment

**Hold publication pending process fixes.** Five P2 findings remain open:
four inherited process gaps and one startup-gate weakness added by this branch.
No critical/high exploit was confirmed. The current candidate's eight green
CI jobs, valid real Windows startup results, and successful local quality run
remain real evidence; they do not establish that the whole release process
fails closed or can recover from interrupted publication.

This is a new process review at `75ba1f88a09553b7e1a83d5bfe1836232f24e01b`,
compared with local baseline `271aa526f827602704b4e36e9b5c92352624752e`.
Earlier readiness statements covered functional/metadata/startup checks and
were too broad when read as approval of the entire publishing process.

Method: three independent read-only host-agent reviewers covered publication,
verification evidence and package integrity; the coordinator checked source,
repository settings and reproduced the key failures. This is not a successful
five-CLI/three-round cross-examination. That earlier live run failed quorum.
No new live model calls, production/TestPyPI uploads, workflow dispatches,
commits, pushes or remote configuration changes were performed for this review.

The scope follows the whole process chain: PR checks and evidence, package
construction/installation, tag admission, publishing identity/approval,
canonical and alias uploads, GitHub release creation, retries and recovery.
It is a focused process audit, not another line-by-line audit of all runtime
modules. Five changed process/configuration files were triaged, with unchanged
release workflows, Makefile targets, verifiers, mutation/sandbox tests and
remote policy inspected as adjacent context.

| Finding | Severity | Confidence | Origin |
| --- | --- | --- | --- |
| Publication does not require successful quality checks for the tagged commit | P2 | High | Pre-existing |
| Partial publication cannot reliably recover by rerunning failed jobs | P2 | High | Pre-existing |
| An unhandled startup exception can count as expected rejection | P2 | High | Added in this PR |
| The containment assertion can certify zero containment tests executed | P2 | High | Pre-existing |
| Hosted CI does not execute the full mutation gate | P2 | High | Pre-existing |

## 1. Publication is not bound to successful CI for the tagged commit

**Locations:** `.github/workflows/release.yml:21-28`, `:82`.

The release build checks tag/version equality and that the commit is an
ancestor of main. It then builds/verifies distributions and smokes the installed
wheel; it neither runs the full quality suite nor requires successful hosted
checks for that exact commit. The publishing job depends only on this build.

Read-only GitHub inspection of effective main-branch rules returned only
`required_signatures`. There is no required CI rule, and classic branch
protection returned404. Thus repository policy does not supply the missing gate.

**Trigger:** a signed main-branch commit still builds and starts but has failed
or pending behavioral/Windows/security tests. A matching tag starts publication;
the normal PyPI environment approval can authorize it despite those test states.
This is an operator-error/process-enforcement path, not proof of an external
unauthenticated publishing exploit.

**Impact/blast radius:** all three PyPI projects and the downstream GitHub
release can be produced without the intended tested-commit invariant. Current
HEAD did pass CI; this finding does not claim it was published or failed tests.

**History:** ancestry guard from `63270872`; unchanged relative to baseline.

**Fix:** require successful reusable quality jobs or verify the required check
set for the exact tagged commit before issuing publishing authority. Reject
missing, pending, failed and mismatched-commit evidence. Test those rejection
paths; main ancestry and a human approval are not substitutes for them.

Evidence: `/tmp/afriend-process-review-main-rules.json`, inspected workflow
control flow, and `/tmp/afriend-process-review-pr.json`.

## 2. Partial publication is not safely retryable

**Locations:** `.github/workflows/release.yml:103-118`, `:122`, `:153`.

Canonical `afriend` and former-name `adversarial-friends` uploads share one job.
If canonical publication succeeds and the alias upload fails, rerunning that
failed job repeats the successful canonical upload first. PyPI's duplicate-file
rejection prevents reaching the failed alias or downstream jobs.

The exact pinned publisher action
`dc37677b2e1c63e2034f94d8a5b11f265b73ba33` defaults duplicate skipping to false;
the workflow does not override it. Tests explicitly assert no `skip-existing`.

**Reproduction:** real Twine7.0.0 uploaded minimal fixture wheels exclusively to
a loopback HTTP registry. Canonical upload returned200, alias returned503, and
the retry's canonical upload returned400 duplicate:

```text
First job steps: [0, 1]
Rerun failed job steps: [1]
Requests: canonical200, alias503 (five attempts), canonical400
Published fixture set: canonical only
```

The coordinator independently reran the reproduction and asserted these results.
No public registry was an upload destination. This proves Twine behavior and
job restart ordering, not live OIDC/PyPI operation.

**Impact/blast radius:** a transient outage can strand a partially published
version across the three projects and block GitHub release creation. Interruption
between wheel and sdist uploads also requires a defined recovery path; splitting
package jobs alone does not solve every within-package interruption.

**History:** bundled upload steps from `c8dc8349`; unchanged relative to baseline.

**Fix:** isolate successful publication boundaries into dependent jobs and add
safe idempotent recovery for already-existing files, checking their hashes
against the original verified artifacts. Do not blindly skip arbitrary existing
files. Exercise canonical/alias and wheel/sdist interruption cases locally.

Evidence: `/tmp/afriend-local-publish-retry-repro.py`,
`/tmp/afriend-local-publish-retry-result.json`,
`/tmp/afriend-local-publish-retry-repro.log`,
`/tmp/afriend-pinned-pypi-publish-action.yml`.

## 3. Startup crashes can count as expected parser rejection

**Location:** `ci/provider_startup.py:60-61`.

Rejection requires exit1/2 and the configured sentinel anywhere in output.
An unrelated unhandled exception that echoes argv therefore qualifies.
The coordinator invoked the real process runner with:

```python
[sys.executable, "-c",
 'import sys; raise RuntimeError("startup crashed parsing " + repr(sys.argv))',
 "afriend-startup-invalid"]
```

`check_launch(..., expected="rejection", diagnostic="afriend-startup-invalid")`
returned successfully with exit1 and a real Python traceback. There was no
mock process result. A CLI whose version/help still work but whose invalid-value
path unexpectedly crashes can consequently receive a green startup result.

**Impact/blast radius:** the shared negative-probe assertion used by all four
Windows CLI jobs. Saved real native runs currently contain valid parser errors;
this finding does not reclassify those observed successes as crashes.

**Fix:** require the measured provider-specific invalid-value diagnostic and
option context, distinguishing it from an unhandled startup exception. Add a
regression for an argv-echoing crash, not just an error without the sentinel.
Authentication/model calls remain outside the agreed startup scope.

**History:** helper introduced in `92164e0`; this weakness is new to the PR.

## 4. The containment gate can claim success with no containment execution

**Location:** `ci/assert_sandbox_tested.sh:9-17`.

The gate only searches output for the literal skip reason
`no OS sandbox mechanism`. It does not require any named containment test to
have passed or even run. Two coordinator reproductions used real pytest:

1. `PYTEST_ADDOPTS='-k missing_system_path' bash ci/assert_sandbox_tested.sh`
   selected only one argument-construction unit test, yet printed
   `containment tests ran.` and exited0.
2. A temporary pytest plugin marked every collected case skipped with another
   reason. All47 cases skipped; the gate again exited0 and reported execution.

No production test file or gate was edited. The plugin existed only under
`/tmp` and was removed automatically. These are fault-injected selection/skip
conditions, not evidence that the current hosted containment runs skipped.

**Impact/blast radius:** one shared gate invoked in each of the three Linux
matrix jobs can give false assurance after selection/marking changes.

**History:** gate from `4389e5a8`; unchanged relative to baseline.

**Fix:** explicitly require key real containment node IDs to pass using
structured pytest outcomes. Reject omitted, deselected, skipped, errored and
failed required cases. Clear or override test-selection settings deliberately
rather than trusting arbitrary inherited options.

Evidence: `/tmp/afriend-parent-containment-false-green.log`,
`/tmp/afriend-parent-all-skipped-false-green.log`,
`/tmp/afriend-process-review-skip-summary.txt`.

## 5. Hosted CI does not enforce mutation-survivor detection

**Locations:** `.github/workflows/ci.yml:107-114`, `Makefile:42`, `:76`.

`make quality` runs the complete targeted mutation probe, but the hosted
workflow does not. Normal pytest validates anchor matching and mocked probe
engine behavior; it does not apply and test all16 mutants. Weakening an
assertion so a mutant survives can therefore coexist with green hosted checks.

The current implementation's locally recorded16 kills are valid. The gap is
future enforcement: the CI result does not independently maintain that
release-quality invariant. This is not evidence of a current surviving mutant.

**Impact/blast radius:** the CI/release assurance for all16 targeted decisions,
including provider-failure classification and envelope handling.

**Fix:** execute the full probe at least once in hosted Linux CI, fail on
survivors/broken entries, and serialize source mutation against other test or
build operations in that checkout.

**History:** omission predates this branch.

## Checked boundaries and rejected findings

- Six-distribution strict metadata and isolated installation verification passed
  offline in a temporary copy of the reviewed commit. Canonical runtime/assets
  match source, no runtime dependencies are declared, aliases pin exactly
  `afriend==0.13.0`, and version/plugin projections agree.
- A proposed missing-distribution-CI finding was rejected: Linux pytest actually
  invokes the real `ci/verify_release_distributions.sh` through
  `tests/test_alias_distributions.py:26`. It is covered indirectly.
- No tested/published-HEAD mismatch was confirmed for current evidence: the
  readiness report identifies the tested implementation commit and subsequent
  changes were documentation only.
- The latest-by-default installation policy and four explicit repository version
  overrides match the user's instructions. No harness pinning is proposed.
- Release actions are SHA-pinned; build has no publishing identity; publication
  consumes artifacts from its own run; GitHub release creation waits for the
  publishing chain. Default workflow token permissions are read-only.
- Main `pypi` approval exists. The `pypi-afriends` environment has different
  protections, but PyPI administrative publisher policies were not accessible;
  no unauthorized-upload claim is made from that asymmetry alone.

## Limits and disposition

This pass used offline fault injection and read-only live metadata. It did not
test actual OIDC token acceptance, TestPyPI/production publication, privileged
PyPI publisher administration, or authenticated model responses. Runtime safety
limits already documented for Windows are not newly discovered process defects.

No fixes have been applied by this review. The production checkout and PR head
remain unchanged. The next work is remediation plus regression tests for these
process findings, followed by rerunning the relevant CI and any explicitly
authorized publication rehearsal. Green candidate CI alone must not be described
as an adversarial clearance of the entire release process.
