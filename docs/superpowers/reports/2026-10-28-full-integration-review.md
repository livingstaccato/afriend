# Full integration review — afriend 0.13.0 working tree

## Verdict and scope

**Remediation update:** all seven findings below (two P1, four P2, one P3)
are resolved in the working tree with regression coverage. See the
[remediation and verification record](2026-10-28-integration-remediation.md).
For current release readiness, see the
[release audit](2026-10-28-release-readiness.md): unrestricted quality checks and
native Windows startup verification subsequently passed. The original review
below preserves the pre-fix findings and evidence;
its source line numbers and verification results describe that earlier snapshot.

The user requested all current uncommitted changes plus integration with the
rest of the repository, in default report mode. Review covered changed runtime,
canonical adapters, generated projections, new tests, release metadata, current
docs/diagram changes, and adjacent unchanged code in CLI/roster/readiness,
authority, dispatch/confinement, process execution/cleanup, envelope recovery,
normalization, judging, qualification, persistence/resume, reporting/status,
and model inventory. Deep inspection prioritized trust boundaries and observed
failures; this does not claim a line-by-line proof of every source/test file or
third-party implementation.

Three independent read-only reviewers examined adapter integration, security and
lifecycle, and protocol/test effectiveness. The host independently reproduced the
false-clean normalization and the lost schema diagnosis. This was host-agent
code review plus offline reproductions and saved live evidence; no additional
live model calls or new afriend report run were performed. Available tool
execution remains restricted; the prior five-friend live run is incomplete.

Baseline context: local `origin/main` at `271aa526` and HEAD `212de107`, plus all
current tracked/untracked changes. Some findings predate the uncommitted patch;
these are included because the user explicitly requested the rest of the code.

## P1 — an older fenced answer can override the final answer

**Location:** `src/afriend/normalize.py:252-265`.
**Confidence:** high. **History:** pre-existing relative to `origin/main`.

NDJSON unwrapping reverses matching events to place the newest answer first.
However, `_candidate_sources()` scans every fenced block before scanning bare
JSON in the combined text. `prefer_order=True` therefore preserves fence order,
not event order. An older fenced answer is accepted before a newer bare answer.

Reproduced through both canonical Pi and Codex envelopes:

1. Older fenced `{"no_findings":true,"findings":null}`.
2. Newer bare, schema-valid findings.
3. Normalization returns the older clean payload with `succeeded=True`.

The reverse case also returns stale findings instead of a final clean answer.
Pi events were both eligible assistant `message_end` events with
`stopReason="stop"`, followed by `agent_settled`.

**Impact:** real final defects can disappear, and downstream gate logic can use
a false clean result. This is independent of the new wildcard path feature.

**Correction:** preserve event boundaries and fully extract/validate each event
from newest to oldest. Add regressions for both fenced/bare directions through
Pi and Codex, retaining existing unbalanced-prose JSON recovery behavior.

**Coverage gap:** `tests/test_envelope_fixtures.py:364` does not establish its
claimed Pi precedence property. Its earlier event has `stopReason="pending"`
and is excluded; its `WRONG-ORDER` marker is outside the JSON and would be dropped
by extraction anyway. Distinct eligible payloads are required to test ordering.

## P1 — model inventory bypasses the safe executable resolver

**Location:** `src/afriend/models.py:89-92`.
**Confidence:** high. **History:** pre-existing relative to `origin/main`.

`list_models()` constructs `[adapter.binary, *adapter.models_argv]` and passes
it directly to `subprocess.run`. Loaded inventory adapters retain bare binary
names (`agy`, `opencode`, `pi`). Unlike readiness and dispatch, this path does
not call `execresolve.safe_which()`.

**Trigger:** on Windows, a hostile checkout contains a same-named provider
executable and the operator runs `afriend providers models pi` from it. Bare
CreateProcess executable lookup can select the checkout executable ahead of the
intended PATH installation. Filtered child environment does not fix executable
selection. This contradicts the repository's stated CWD-safe spawning invariant.

**Correction:** resolve and require a safe executable before invocation; execute
its absolute path, with the existing missing-executable error behavior. Add an
inventory regression covering rejected CWD-only matches. This is verified as a
code-path omission; native Windows execution was not available for this review.

## P2 — OpenCode effort mappings use a rejected CLI flag

**Location:** `src/afriend/assets/adapters/opencode.toml:35-37`.
**Confidence:** high. **History:** pre-existing mapping retained by the branch's
OpenCode 2.1.4 compatibility update.

All advertised low/high/max settings append `--variant`. The saved live run
failed immediately with `Unrecognized flag: --variant in command opencode run`.
Installed `opencode run --help`, inspected using a temporary HOME and no model
call, documents variants inside `--model provider/model#variant`; it does not
accept `--variant`.

**Impact:** selecting these effort settings, including the attempted thorough
cross-examination, prevents OpenCode from reaching its provider.

**Correction:** construct a supported model/variant argument, or withdraw effort
support until it can be represented accurately. Validate default and explicitly
selected models and presets against the actual installed parser. Current tests
using a Python child do not establish real OpenCode argv compatibility.

## P2 — Pi's managed Node runtime disappears after XDG redirection

**Locations:** `src/afriend/dispatch.py:529`, `src/afriend/childenv.py:145`,
`src/afriend/assets/adapters/pi.toml:194-199`.
**Confidence:** high. **History:** Pi adapter introduction (`5b9e0b5`), before the
current uncommitted credential-directory repair.

The installed Pi launcher resolves managed Node beneath
`${XDG_DATA_HOME:-$HOME/.local/share}/pi-node/current/bin`. Dispatch replaces
`XDG_DATA_HOME` with private state; the policy grants Pi's install/versions
folders, but no managed Node tree.

**Reproduction:** copied the exact installed launcher into temporary files,
provided a fake managed Node that only prints a marker, and removed usable
system Node from PATH. Before private-env redirection it exited0 with the
marker; after redirection it exited127 (`env: 'node': No such file or directory`).
Constructed policy also lacked the managed-runtime read grant. No model or
network call was needed. This host's system Node masks the condition in live runs.

**Correction:** resolve and preserve interpreter selection before generic XDG
redirection, grant only the required runtime tree read-only, and test a launcher
without usable system Node. The completed plan explicitly requires this managed
installation shape to work.

## P2 — Claude spend exhaustion loses its diagnosis and quota classification

**Location:** `src/afriend/assets/adapters/claude.toml:77-79` and its absent quota
declaration. **Confidence:** high. **History:** pre-existing relative to baseline.

Saved live Claude stdout has `is_error=true`, `api_error_status=429`,
`api_error="usage_limit_reached"`, and
`result="You've hit your individual spend limit …"`; stderr is empty.
The envelope only declares the successful `structured_output` path. There is
no quota marker for this captured failure.

Offline replay yields generic missing-findings errors, no provider error, and
`UNKNOWN` classification. The audit shows only `failed: exit1`, and the exhausted
friend was retried in the next round before repeat suppression stopped it.

**Correction:** extract the captured structured error result and classify the
specific captured quota marker, rather than treating every429 as the same case.
Report actionable allowance remediation. This explains the observed failure;
it does not establish a broken login or rejection of Claude's denial flags.

## P2 — failed normalization hides a precise inner schema error

**Location:** `src/afriend/normalize.py:385-386`.
**Confidence:** high. **History:** pre-existing relative to baseline.

When unwrapped text fails validation, normalization always replaces that result
with the raw retry's diagnosis, even when the raw retry recovers nothing better.
The saved Pi/GLM critique had a list-valued `location`; the contract requires a
string or null. Its envelope extraction succeeded.

Normalizing the extracted answer reports:

```
findings[0].location must be string or null, not list
```

Normalizing its full stream instead reports:

```
payload has neither 'findings' array nor no_findings marker
output was structured JSON but contained no findings; the adapter may need an envelope path
```

**Impact:** model schema noncompliance is misdiagnosed as adapter envelope failure,
concealing the actual fix and making unsuccessful reviews harder to triage.

**Correction:** retain the inner schema diagnosis when raw fallback cannot recover
a successful or more relevant payload, while preserving existing successful
fallback behavior. Add a wrapped malformed-answer regression.

## P3 — skipped rows create false filesystem-exposure warnings

**Location:** `src/afriend/report.py:574`.
**Confidence:** high. **History:** pre-existing relative to baseline.

The report excludes only HTTP rows from executable filesystem warnings.
`persist_skip` records `transport="not-dispatched"` and `os_confined=False`.
Consequently, round-three skipped OpenCode/Pi-testability rows put both names in
the exposure warning even though every actual dispatch for them was confined.

**Correction:** exclude deliberately non-dispatched rows and derive actual
execution exposure from dispatched audit records. Keep genuine unconfined
executions visible, including executions whose write protection is true.

## Saved live evidence and interpretation

Run:
`/tmp/afriend-five-crossexam-y8tzqei0/runs/run-20261028T124037-42d7aefc`.

Actual execution used five workers, four CLI families, three rounds, and10
attempted calls. Only Codex produced a usable critique. Pi/GLM subsequently
produced usable judging verdicts; this does not retroactively make its critique
successful. Two Pi/Kimi calls timed out while still investigating repository
files. Timeouts alone do not prove a parser or credentials bug.

The run's10 non-OK audit rows include three deliberate skips; they are not10
failed model calls. Actual calls:10; successful responses:3; failed/timed-out
calls:7. Exit12 reflects the five-friend critique quorum not being met.

The two recorded claims were upheld by a reduced judge set after failures;
that incomplete run is not a complete five-friend adjudication. Managed Node
was independently reproduced as above. The precedence-test weakness is valid,
and the expanded review additionally found the actual false-clean parser bug.

Credential-bearing read grants remain a documented architectural exposure:
a compromised friend can read credentials that its CLI needs. No secret values
were copied into this report, and no new prompt-injection/exfiltration experiment
was performed. This known risk is not treated as proof that every boundary is safe.

## Verification and limits

Fresh local suite: **2,719 passed,31 skipped**, one existing multiprocessing
fork warning, in77.53 seconds. Nineteen named OS/network/build-dependent cases
were explicitly deselected because this execution environment blocks their
requirements. Their names and full command output are in
`/tmp/afriend-integration-review-tests.log`. No test was weakened or source
implementation changed for this review.

Focused independent checks:73 passing envelope/Pi E2E/confinement cases;35
passing model-listing/Pi-confinement/Claude-marker cases (these groups overlap).
Additional process/policy tests passed available Linux cases; Windows-native
cases remained skipped. Standalone minimal repros confirmed false-clean
normalization and lost inner validation errors.

These passing tests do not cover the confirmed bugs. Pi E2Es use a strict
synthetic executable and explicit unsandboxed fallback. Pi policy tests replace
process execution; OpenCode policy tests substitute the wrapper and run a Python
child. They do not prove native provider compatibility or live OS enforcement.
No fresh Windows/macOS host verification, full unrestricted quality run, or new
live model calls were performed during this review. The earlier unrestricted
run remains historical evidence, not a replacement for resolving these findings.

No commit, tag, push, merge, or publication occurred.
