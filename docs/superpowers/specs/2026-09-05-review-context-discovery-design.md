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

The existing plugin-sync, documentation, diagram, and distribution checks
remain required after updating the canonical skill assets and their projection.
