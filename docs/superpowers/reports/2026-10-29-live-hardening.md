# Live-review hardening disposition

The revised live review raised a confirmed Windows interpreter-search exposure,
two gate-hardening issues, and documentation/evidence concerns. This record
tracks remediation; native Windows and final hosted verification are pending.

## Windows npm Node search — true positive

A trusted Pi/Codex JavaScript `.cmd` launcher can fall back to bare `node`.
Windows cmd searches the checkout implicitly when the protection variable is
absent. Pi model inventory removed even a parent protection variable; readiness
probes inherited the default environment before review confinement decisions.
An untrusted checkout could therefore supply `node.exe` despite safe resolution
of the launcher itself. Codex's affected path is readiness, not model listing.

Independent verification traced the real subprocess boundaries and reproduced
loss of protection on Linux while simulating executable discovery. The native
search contract is documented by [Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-needcurrentdirectoryforexepathw)
and the fallback by [npm](https://github.com/npm/cmd-shim/blob/main/lib/index.js).
This source/boundary verification did not claim a native Windows exploit run.

The fix forces `NoDefaultCurrentDirectoryInExePath=1` in filtered child
environments and inherited readiness probes. It preserves explicit PATH
entries, wrappers and sibling interpreter selection. New native tests run an
unsafe control selecting a harmless checkout copy of real `node.exe`, then
exercise protected inventory/probes and custom wrappers/sibling Node. They fail
in CI if required Node is missing. Native CI must pass before this fix is proven.

## Rejection-envelope false green — reproduced and fixed

The previous crash-pattern blocklist accepted valid parser output followed by
unknown failure text, including a Go-style panic. Twelve provider/trailer cases
failed before the repair. Validation now full-matches the entire measured error
envelope and known trailers, retaining original raw output. OpenCode may prepend
only the exact help text previously measured by the run. Existing valid LF/CRLF
captures and crash regressions remain accepted/rejected as intended.

## Release evidence-name drift — hardened

The gate depended on implicit matrix display names and duplicated fixture names.
A workflow rename could pass local fixtures but block publication. Required
quality and Windows job display names are now explicit. A test derives display
names, matrix members and step names from the actual workflow and checks the
gate's required evidence. The regression failed before explicit naming and
passes afterward. This was an availability/maintenance gap, not a CI bypass:
missing required names already caused the gate to fail closed.

## Evidence and documentation concerns

The readiness audit now has one current status, explicit UTC/Pacific dating,
durable CI links, named workflow artifacts, explained historical shallow-clone
skips, and [six published-file hashes](2026-10-29-testpypi-files.json).
The [live TestPyPI record](2026-10-29-live-testpypi.md) distinguishes successful
rehearsal identities from untested production identities and later source edits.
OpenCode's document-only review scope is an access limitation, not proof that
unseen source is wrong. Its unverified statements do not constitute refutation.

Independent follow-up review found no concrete defect in the current fixes.
Isolated `make quality` passed: **2,944 passed, 36 skipped**, one existing
warning; all **16 mutants killed**, zero survivors/skips. Static, sync, diagram,
wheel and six-distribution checks passed. Native hosted CI remains pending. The five-worker cross-examination has not yet obtained five usable
critiques because Pi/GLM timed out and returned invalid judging output. Failed
and cancelled runs are retained, and no combined quorum is claimed.

## Latest eval harness

The remaining Codex eval-container pin at 0.154.0 was removed. Default build,
login and run commands refresh `@openai/codex@latest` once with cache disabled;
`--codex-version` provides an optional exact override and separate image tag.
Summaries record requested and actual versions; dry runs call nothing. Existing
authentication and isolation controls remain intact. Fifty-four focused tests
and independent review passed. A real latest image built successfully and ran
Codex 0.165.0 without network or credentials: `--version` exited 0, deliberately
invalid sandbox selection exited 2 with the expected parser diagnostic. No new
login or authenticated eval-suite execution is claimed.
