# afriend 0.13.0 release audit

A subsequent adversarial process audit found five release-enforcement gaps.
All five are addressed in the current remediation candidate. Integrated local
`make quality` passed: **2,913 passed, 31 skipped**, one existing warning, and
**16 mutation probes killed, zero survivors/skips**. All portable static, diagram,
package and isolated-install gates passed. The corrected implementation `f153ec7` passed all eight jobs in
[CI run40799404634](https://github.com/livingstaccato/afriend/actions/runs/40799404634):
Linux Python3.11/3.12/3.13 each **2,911 passed,33 skipped**; native Windows
**2,803 passed,141 skipped**. Hosted mutation results were16 killed, zero
survivors/skips. All four real latest Windows startup jobs passed. The three
real Twine loopback recovery tests also passed on Linux and native Windows. The earlier measurements below
remain historical evidence, not clearance of the revised release process. See
[process review](2026-10-29-release-process-review.md) and the
[release procedure](../../release-process.md). No publication has been performed.

## Earlier implementation verification

The implementation through `960ffc3` is verified for review and merge under the
agreed startup/rejection validation scope. PR #9 remains draft and mergeable.
It has not been merged, tagged or published; this audit does not authorize those
actions or claim absolute correctness.

## Change and documentation coverage

The release adds Pi as the sixth adapter, updates OpenCode v2 integration, and
fixes envelope event ordering, inner schema diagnostics, safe model-inventory
lookup, managed Pi Node selection, Claude quota diagnosis and skipped-friend
exposure warnings. The real Windows gate also exposed and verified the repair
for npm batch launchers corrupting Claude's inline JSON schema. Standard native
npm launchers are resolved directly; custom profiles/arguments are preserved.

`CHANGELOG.md` has a populated `## 0.13.0` section covering these changes,
offline E2Es, the latest-by-default native Windows startup matrix and the
quoting fix. README and installation/troubleshooting guidance describe current
provider behavior, exact version-override variable names and Windows limitations.
Earlier review reports are preserved as historical evidence and now point here;
the completed Windows plan is marked accordingly.

The components, run-flow and cross-examination state diagrams were updated
together with their PNG/SVG renders and digest manifest. All six architecture
diagram sources render successfully; documentation tests check committed render
presence, visible-label errors and PNG/source digest consistency. No new runtime
behavior was introduced by this status-documentation reconciliation.

## Versions and distributions

Version synchronization passes at **0.13.0** across `VERSION`, the dynamic
canonical package, Claude/Codex plugin manifests, marketplace metadata and both
compatibility distributions. `adversarial-friends` and `afriends` depend exactly
on `afriend==0.13.0`. The installed checkout reports `afriend 0.13.0`.

Local `make quality` passed on the frozen implementation: **2,817 passed,
31 skipped**, one existing multiprocessing warning. All16 mutation probes were
killed; formatting, lint, strict typing, source-length, plugin/version sync,
diagram, wheel asset/install and isolated six-distribution checks passed.
Evidence: `/tmp/afriend-native-fix-final-quality.log`.

## CI and real Windows startup evidence

[CI run40790113769](https://github.com/livingstaccato/afriend/actions/runs/40790113769)
passed all eight jobs at `960ffc3`:

| Job | Passed | Skipped |
| --- | ---: | ---: |
| Linux Python3.11 | 2,815 | 33 |
| Linux Python3.12 | 2,815 | 33 |
| Linux Python3.13 | 2,815 | 33 |
| Native Windows suite | 2,710 | 138 |

The four additional Windows startup jobs use installed real npm CLIs and
afriend's resolver, canonical argument construction and process runner. Every
job selected `latest`; no version override was active. All twelve probes passed:

| Harness | Installed version | Version/help exits | Deliberate invalid-value exit |
| --- | --- | --- | ---: |
| Claude | 2.1.312 | 0 / 0 | 1 |
| Codex | 0.165.0 | 0 / 0 | 2 |
| OpenCode | 2.2.0 | 0 / 0 | 1 |
| Pi | 1.4.0 | 0 / 0 | 1 |

Each rejection included the required diagnostic; no probe timed out or reported
suspected orphan processes. Native Windows process-tree termination and suspended
startup tests also passed in the ordinary Windows suite. Linux CI additionally
asserted real OS-containment tests ran. The138 Windows skips include POSIX-only
tests; the four real startup jobs have no skip/continue-on-error route.

Artifacts `windows-startup-claude`, `windows-startup-codex`,
`windows-startup-opencode` and `windows-startup-pi` record the selector, npm/Node
versions, executable paths, argv, output, exit codes, timing and cleanup.
Local evidence: `/tmp/afriend-windows-startup-final/` and
`/tmp/afriend-windows-startup-final-ci.json`. These observed versions are evidence,
not pins: future jobs follow `@latest` unless an operator explicitly configures
one of the documented `AF_STARTUP_*_VERSION` repository variables.

## Remaining release actions and limits

- PR #9 is still draft; no formal GitHub review approval was recorded at audit
  time. Independent host-agent reviews and their regression evidence are not
  represented as GitHub approvals.
- The current candidate has not run the publishing TestPyPI rehearsal. Its
  workflow exists and succeeded previously on a different commit. Local isolated
  package verification does not prove a new OIDC publication will succeed.
- At audit time, `v0.13.0` did not exist and PyPI returned404 for version0.13.0
  of all three projects. Publishing requires a merged main-branch commit, a
  matching version tag, and the release workflow's successful build/publish
  sequence. The repository's `pypi` environment also requires approval from
  `livingstaccato`; that protection was checked through the GitHub API.
  No release was attempted during this audit.
- The Windows gate establishes real startup and diagnostic rejection without
  credentials or model calls. It does not claim authenticated reviews, the
  previously incomplete five-worker cross-examination, AGY installation, or a
  new native macOS validation run. Ollama is outside the executable-CLI matrix.
- Documented Windows security limits remain: no OS filesystem confinement,
  explicit unsandboxed opt-in for affected providers, inherited run-directory
  ACLs and weaker filesystem-race protection. They were not silently resolved
  by the startup tests.

The next integration steps are review/ready status, merge, and the chosen
publication rehearsal/release sequence. Keep readiness claims within the
verified scope above.
