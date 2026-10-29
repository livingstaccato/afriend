# Failed-friend recovery guidance verification

The review skill previously documented readiness widening, truthful failure
reporting and model inventory. Runtime quota diagnostics suggested a friend with
separate allowance. It did not explicitly distinguish account spend limits or
specify the replacement/new-run procedure.

An independent agent read the original skill and troubleshooting reference. It
identified those missing instructions before edits. Canonical guidance now
covers diagnostic classification, account versus model quota, feasible named
replacements, reuse of existing authorization, preserved counts/lenses/rounds,
separate external-tool authority, new runs for changed rosters, and preservation
of partial results without combining runs to manufacture quorum. The plugin
projection was regenerated from the canonical assets.

After edits, the independent agent applied the guidance to four cases:

| Case | Expected behavior | Result |
| --- | --- | --- |
| Claude individual spend cap; fresh Codex replacement already approved | Reuse approval; preserve five roles and three-round ceiling; disclose correlation; new run, not resume | PASS |
| Model-specific quota; alternative not yet listed | Inspect current inventory before proposing a model | PASS |
| Replacement OpenCode requires an external-tool grant not supplied by user | Recheck policy and obtain explicit grant; do not infer it from review intent | PASS |
| A second fresh Codex/ops duplicates an existing ledger identity | Use a distinct lens consistent with the approved reliability role; do not invent a model | PASS |

Existing skill-layer, projection and documentation tests passed. These are
agent application checks and deterministic package checks, not a claim that
all real host CLIs selected the skill correctly. The Claude spend-limit failure
and the user's approved replacement were also exercised in the ongoing live
release review, whose completion is recorded separately.
