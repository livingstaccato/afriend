# Review Context Discovery Design

## Goal

Let afriend distinguish a code-review finding set, an implementation under a
plan, and an ordinary artifact review when the evidence supports that
distinction. The selected context must be visible before dispatch, frozen into
the run record, and stated to every friend. The router must remain unable to
invent an artifact, repository, authority grant, or relationship.

## Separate discovery from review context

Two decisions have different owners and lifetimes:

- **Discovery policy** controls how a host skill finds an artifact and its
  relationship to the task. It is a user preference with values
  `evidence-only`, `session-assisted`, and `confirm-always`.
- **Review context** describes what the run asks friends to evaluate. It is
  one of `artifact-review`, `code-review-findings`, or
  `implementation-of-plan`. It belongs to one run, not to the user's general
  configuration.

The default discovery policy is `session-assisted`. A user may change that
default persistently or for the current host task. Direct CLI invocations
remain explicit: they accept a supplied artifact and default to
`artifact-review` unless the caller selects a review context.

## Evidence contract

`evidence-only` may use an explicit artifact path, explicit `--repo`, the
artifact's repository membership, and a directly named plan or review file.
`session-assisted` additionally may use complete text already supplied in the
current session, including a review the host materializes verbatim into a
scratchpad file, and an explicitly identified task artifact. It may inspect
candidate paths only to present them when ambiguity remains.

`confirm-always` follows the same discovery rules but requires the user to
select the artifact and context before the normal run preflight.

No policy may infer a missing file from a vague reference, reconstruct
incomplete review text, select one of several candidates silently, create a
repository binding, or enable a provider or external tool. A single
unambiguous candidate may be selected automatically in `session-assisted`.

## Context semantics

| Context | Required evidence | Friend instruction |
| --- | --- | --- |
| `artifact-review` | Artifact path | Critique the supplied artifact under the selected lens. |
| `code-review-findings` | A complete code-review finding set and a selected repository snapshot | Treat every finding as a claim to validate against the frozen source; review the finding's substance, not merely its prose. |
| `implementation-of-plan` | An implementation snapshot plus the plan/spec it implements | Compare the implementation with the stated requirements; identify missing, contradictory, or unsafe behavior. |

The router displays the context and each evidence source in its preflight. A
run persists the context and evidence summary in `run.json`; the report shows
the same summary. The prompt builder receives the context contract so all
friends have the same objective while retaining their separate lenses.

## Authority language

An adapter whose provider-managed integrations cannot be verified disabled is
not known to have those integrations enabled. Its correct status is
`external_tools=uncontrolled`: tools, plugins, apps, or MCP servers **may
remain available**. afriend cannot verify their invocation-local denial.
Every roster, warning, and troubleshooting message must use this conditional
language. A provider-scoped external-tool grant authorizes that uncertainty
for only the named run; it does not change provider defaults.

## Repository review-access contract

A repository-scoped review is a promise that every admitted repository-scoped
friend can inspect the frozen checkout it is asked to judge. Launching a
provider successfully is not evidence that this promise was kept.

Before dispatch, afriend must validate the effective review boundary for each
selected friend: its own unavoidable startup reads, its private isolation
directory, and the repository snapshot must all be readable under the
combined outer OS confinement and provider sandbox. The check must use the
same executable, environment allowlist, confinement mechanism, and working
directory that the review would use. A probe that merely parses `--help` is
not sufficient when the provider performs additional startup work for an
actual turn.

The validation is fail-closed for crossexam, gate, and loop: a friend that
cannot start and read the frozen checkout is not admitted as a judge, and a
run that then lacks the required independent judges refuses before semantic
review dispatch. `report` may continue with the usable roster, but must state
the omitted friend and access reason prominently.

Runtime failures remain possible after preflight. If an otherwise admitted
friend reports or demonstrates a sandbox/permission access failure while
reviewing, the affected claims are **not assessed — judge access failure**.
They are incomplete, block a gate, and are never transformed into `unproven`
or terminal `discarded`. `discarded` is reserved for repeated, unchanged
attempts by eligible judges that had working access to the evidence; it says
neither that a claim lacks merit nor that a tool failure settled it.

For Codex on macOS, the compatibility allowance must be derived from an
identified, unavoidable startup path rather than granting a broad home or
agents directory. The recorded sandbox profile remains auditable, and the
provider still receives its inner `--sandbox read-only` mode and disabled
apps/plugins. Any necessary path grant is read-only and scoped to the
provider's actual startup dependency.

## Verification

Tests will prove that:

- default session-assisted discovery selects a sole evidence-backed artifact
  and reports its context and evidence;
- ambiguous or incomplete session references do not cause selection;
- evidence-only and confirm-always retain their stricter behavior;
- each persisted review context reaches `run.json`, `report.md`, and every
  friend prompt;
- code-review findings ask friends to validate claims against a frozen
  repository snapshot, and implementation reviews ask them to compare the
  implementation with its plan;
- uncontrolled-provider prose says integrations may remain available and
  never claims they are enabled.
- a repository-scoped friend that cannot complete its real startup or read its
  isolated snapshot is rejected before a crossexam/gate/loop spends review
  calls;
- an access failure discovered during judging leaves its claims explicitly
  incomplete and "not assessed", never discarded;
- the macOS Codex confinement policy admits only the measured startup path
  required for a real review, while still denying unrelated home-directory
  reads and preserving Codex's own read-only mode.

The existing plugin-sync, documentation, diagram, and distribution checks
remain required after updating the canonical skill assets and their projection.
