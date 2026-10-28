# Integration remediation — afriend 0.13.0

All seven findings in the [full integration review](2026-10-28-full-integration-review.md)
are resolved in the uncommitted working tree. This records code corrections and
local verification; publication remains held pending unrestricted verification
and incomplete live-provider evidence.

## Finding dispositions

| Finding | Resolution | Regression evidence |
| --- | --- | --- |
| P1: older fenced answer overrides final bare answer | Preserve envelope answer boundaries; extract each event newest first. Keep the public joined-text helper compatible. | Canonical Pi and Codex streams cover both fence/bare directions, judging, split events, and prose recovery. The existing Pi precedence fixture now has distinct, eligible answers. Ordering regression run before repair: 8 failed, 4 passed. |
| P1: model inventory bypasses safe executable resolution | Resolve through `execresolve.safe_which`, anchor the accepted executable path, and refuse missing executables before launching. | Two regressions failed before repair and pass afterward; existing listing behavior remains covered. Windows-native execution is still unverified here. |
| P2: OpenCode rejects obsolete `--variant` | Remove obsolete effort mappings and advertise `effort_kind="none"`. Presets record the downgrade; explicit unsupported effort is rejected before dispatch. | Adapter/preset tests cover dispatchable defaults and downgrade behavior. Installed native CLI accepted generated default and explicit-model argv with `--help`; no model request was made. |
| P2: redirected XDG hides Pi's managed Node | Resolve Node from the filtered child environment before redirecting state; preserve its absolute PATH selection and grant the selected runtime read-only. Exclude relative/empty PATH entries; preserve POSIX defaults when PATH is absent. | Eight managed-runtime cases cover actual copied launcher behavior, custom state, fallback, symlinks, and hostile PATH entries. The absent-PATH follow-up failed before correction and passed afterward. Policy assertions do not establish real OS confinement. |
| P2: Claude spend limit loses diagnosis | Extract the structured `result` error and classify the precise `usage_limit_reached` marker as quota exhaustion. | Captured sanitized response replay through a real subprocess preserves the provider message and quota classification; generic 429, auth failures, and successful structured results remain distinct. |
| P2: raw retry hides inner schema error | Keep the relevant extracted payload's validation errors when raw fallback yields no better result; successful fallback remains available. | Wrapped malformed-location regressions failed before repair and now preserve the string-or-null diagnosis. |
| P3: skipped rows imply filesystem exposure | Exclude `not-dispatched` records from executable exposure warnings while retaining their audit rows. | Paired confined/unconfined execution cases followed by a skip retain genuine warnings and remove false ones. |

Canonical adapter and reference changes were projected into the plugin using
the synchronization script. README, troubleshooting, preset guidance, and
CHANGELOG describe the new behavior, including the withdrawal of OpenCode's
separate effort override. No `model#variant` workaround is advertised because
afriend's model grammar does not accept that syntax.

## Independent follow-up

Three read-only reviewers examined normalization, security/runtime integration,
and adapters/reporting. Normalization counterexamples passed 27 cases; the
adapter/report group passed 82 tests. The security reviewer caught the unset-PATH
edge case in the initial Pi repair; it was corrected with a red/green regression
before combined verification. No further findings were reported. These are
host-agent reviews, not a completed five-provider live cross-examination.

## Final local verification

- Combined pytest run: **2,760 passed, 31 skipped**, no failures, one existing
  multiprocessing fork warning, in 119.37 seconds. Nineteen environment-dependent
  cases were explicitly deselected: localhost HTTP/server integration, real Linux
  namespace confinement, and two isolated distribution-build checks. Full names
  and output: `/tmp/afriend-seven-suite.log`. Collection totals 2,810 tests;
  README's count matches.
- All **16 mutation probes killed**, zero survived or skipped. Output:
  `/tmp/afriend-seven-mutations.log`.
- Format/lint, strict mypy (96 source files), maximum source length, plugin sync,
  version sync, and rendering of all six diagram sources passed. Output:
  `/tmp/afriend-seven-static-final.log`. Existing rendered diagram updates and
  digests are included in the working tree.
- Six candidate wheel/sdist artifacts rebuilt using cached backends without build
  isolation. Canonical wheel metadata/assets and exact alias dependency pins
  checked. Fresh wheel installations outside the checkout passed version/help
  checks on Python 3.11, 3.12, and 3.13; both aliases passed on Python 3.13.
  Output and SHA-256 hashes: `/tmp/afriend-seven-artifacts.log`; artifacts:
  `/tmp/afriend-0.13.0-release-candidate`.

The first candidate smoke rerun stopped because its temporary virtual
environment already existed. The temporary launcher now recreates those named
smoke environments; the complete rerun exited zero. Product behavior and tests
were not weakened to accommodate this setup issue.

## Remaining release evidence

The restricted execution environment cannot prove the 19 excluded cases or run
the complete isolated quality/distribution gates. Run the prepared command in an
ordinary terminal for this final source snapshot:

```bash
bash /tmp/afriend-0.13.0-release-check.sh
```

That script runs `make quality` and isolated distribution verification; it does
not commit, tag, push, or publish. The earlier successful unrestricted run
predates these seven corrections and is not evidence for the final snapshot.

Offline Pi E2Es, policy tests, and provider failure replay establish their
specific contracts; they do not prove all live providers or native Windows/macOS
behavior. Claude's account spend allowance remains exhausted. Pi/Kimi's live
timeouts and Pi/GLM's schema noncompliance remain observed provider-run failures;
the fixes improve diagnosis without claiming those external outcomes are cured.
The prior five-worker run completed three rounds but failed critique quorum.
No new live model calls, commits, tags, pushes, or publication were performed.

## Subsequent review and coverage exercise

A fresh three-reviewer pass found one additional P2: Node discovery applied the
managed launcher's precedence to npm/manual Pi installations as well. The new
mixed-install regression executed a real npm-style shebang with a stale managed
Node present and failed with exit42 before repair. Dispatch now passes the
resolved executable to discovery; only the measured managed launcher's bounded
signature enables its private Node precedence. Generic entrypoints retain the
filtered PATH-selected interpreter. Managed and symlinked launchers remain
covered.

Follow-up inspection found that reading an executable FIFO could block before
the friend timeout started. A real FIFO regression failed with `TimeoutExpired`
before repair. Inspection now uses nonblocking open, checks the opened
descriptor for a regular file, reads a bounded prefix, and always closes it.
Both corrections passed independent read-only re-review. No additional issue
was reported in that scope.

Additional tests exercise bare-tilde credential roots, missing home/state,
unavailable/directory/symlinked entrypoints, wildcard string fragments,
fixed-index compatibility, unknown-envelope fallback, and the portable
non-POSIX no-op guard. That guard test explicitly simulates a platform decision;
it is not Windows-native evidence.

Final source verification:

- Broad coverage run: **2,770 passed, 31 skipped**, 19 explicitly excluded,
  one existing fork warning, in130.50 seconds. One subsequently added
  fixed-index compatibility test passed separately and its coverage was
  appended. Together these exercise all available cases in the final
  2,821-test collection. Logs: `/tmp/afriend-coverage-final.log` and
  `/tmp/afriend-coverage-final-append.log`.
- Combined runtime coverage: **87.9% lines** (9,998/11,380), **80.8% branches**
  (3,403/4,212). Added/modified executable lines in the working-tree diff:
  **99/99**, with **48/48 branch outcomes** whose source line is modified.
  Untracked `managedruntime.py` is included in full and has100% line/branch
  coverage. This is execution coverage, not proof of every input combination.
  Python subprocess instrumentation was enabled. Reports:
  `/tmp/afriend-coverage-final.json` and
  `/tmp/afriend-coverage-final-html/index.html`.
- Static checks and all six diagram renders passed; all16 mutation probes
  were killed with zero survivors/skips. Logs:
  `/tmp/afriend-final-static.log` and `/tmp/afriend-final-mutations.log`.
- Six offline candidate distributions rebuilt after the runtime fixes;
  installed-wheel checks passed on Python3.11/3.12/3.13 and both aliases on
  Python3.13. Log: `/tmp/afriend-final-artifacts.log`. The later README count
  and report edits require fresh distributions at release time as usual.

The19 excluded cases were also attempted directly, together with platform
tests: **10 failures, 9 setup errors, 7 passes, 20 skips**. Socket creation was
denied, bubblewrap could not create a namespace, and isolated builds could not
fetch unavailable backend packages with network access blocked. The20 native
Windows cases skipped on Linux. Evidence:
`/tmp/afriend-environment-exercise.log`. These limitations remain unresolved
verification requirements; none of the failed cases was changed to pass here.

No PR was created. `gh pr view` could not connect to `api.github.com`, so remote
PR existence was not verified. The changes remain uncommitted. Full unrestricted
quality/distribution verification and Windows-native CI remain required.

## Unrestricted release-check result

The user subsequently ran `bash /tmp/afriend-0.13.0-release-check.sh` in an
ordinary terminal: **exit0 in208.2057 seconds**. This final-source run completed
`make quality`, including the full pytest selection, mutation probes, static
checks, diagram rendering, wheel asset/install checks, and isolated verification
of all three wheel/sdist pairs. The script then independently rebuilt and
verified the six release distributions in
`/tmp/afriend-0.13.0-verified-dist.DXaORn`.

This supersedes the unrestricted Linux quality/distribution blocker described
above. The displayed user-shell output was truncated, so no exact pytest
pass/skip count is inferred from it. This was not a coverage-enabled run and
does not replace the separately measured coverage percentages. It also does
not establish native Windows execution or a successful five-provider live
cross-examination. A draft PR and Windows CI are the next integration steps;
publication remains pending those outstanding checks.
