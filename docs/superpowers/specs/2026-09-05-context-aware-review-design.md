# Context-Aware Review Design

## Goal

Make an explicit `/afriend:review` understand the review chain visible in its
current session. It must distinguish a standalone artifact review from
validating a plan or prior code review against the implementation work that
followed it, and it must make that choice visible before dispatch.

## Scope

The feature applies to the `/afriend:review` skill and the artifacts it gives
to `afriend run`. The CLI continues to require an exact artifact path; it does
not inspect chat history. The host skill resolves session context into a
deterministic, saved composite artifact before invoking the CLI.

The resolver considers only material that is available to the host and names
every selected input. It never treats an implied relationship as a security
grant: repository selection, provider selection, external-tool authority, and
write authority keep their existing rules.

## Concepts

### Evidence item

An evidence item is one readable source with a role, canonical path or
repository identity, and a short display label:

| Role | Examples |
| --- | --- |
| `plan` | a referenced design or implementation plan |
| `review` | a referenced code-review artifact or an afriend report |
| `change` | a diff, commit range, or working-tree change set |
| `repository` | the Git worktree whose snapshot supplies code context |

The host discovers candidates from the configured session window: explicit
paths, task attachments, prior afriend run paths, and recent command-like
references such as `/code-review` or a plan name. Discovery does not fabricate
content or infer a path from a bare label.

### Change set

A change set is plural evidence for implementation work in one repository. It
can contain the uncommitted worktree diff, one or more explicitly referenced
commit ranges, and one or more explicitly linked worktree diffs. The manifest
records each member, its source expression, and its resolved commits or hash.

Automatic grouping is limited to one repository. A cross-repository change
set, an unknown base, an inaccessible worktree, or multiple competing change
sets is ambiguous.

### Review intent

The resolver produces exactly one intent:

| Intent | Inputs | Question sent to friends |
| --- | --- | --- |
| `artifact` | one supplied artifact | What is wrong or missing in this artifact? |
| `validate-plan` | plan + change set | Does this implementation satisfy the plan? |
| `validate-review` | prior review + change set | Are the prior review's claims supported, addressed, or contradicted by the implementation? |
| `validate-chain` | plan + review + change set | Does the implementation satisfy the plan and correctly address the review? |

An explicit artifact path remains authoritative. The resolver adds context only
when the session supplies an unambiguous related chain. It selects
`validate-chain` whenever all three roles form that chain; otherwise it selects
the most specific available validation intent.

## Resolution policy

The persistent session settings define a `review_context` policy:

```toml
[review_context]
enabled = true
sources = "current-task"        # current-task | recent-session
automatic_combine = true
ambiguity = "ask"               # ask | newest | refuse
```

Profiles and a single invocation may override these review-safe choices. They
cannot expand the accessible session window beyond the host-visible task, add
repository access, or grant provider-managed tools.

With the default `ask` policy, the resolver asks before dispatch whenever two
or more candidates plausibly fill the same role, a change set crosses a
repository boundary, or it cannot establish a relationship. `newest` chooses
only among candidates in the same repository and reports that choice;
`refuse` requires an explicit artifact or context selection.

## Composite artifact

For a validation intent, the host writes an immutable Markdown composite into
the run scratchpad. It contains:

1. a `Review intent` line stating the exact question;
2. an input manifest with roles, paths, repository root, commit/range or
   worktree identities, and hashes;
3. the complete plan and/or review text;
4. each change-set member with a labeled diff or commit-range summary; and
5. an instruction to distinguish unassessed evidence from evidence that
   refutes a claim.

The composite is the CLI artifact. The selected repository is passed through
the existing `--repo` route, so friends inspect the same immutable snapshot
that the manifest identifies. The run report and `run.json` retain the
composite path and input manifest so a user can reconstruct why the review
was combined.

## Session preflight

On the first review in a host task, and before a requested new loop iteration,
the skill states the resolved intent before it dispatches. For example:

> About to start afriend to validate `review.md` against 3 implementation
> changes in `/repo` in report mode with quick. Inputs: `plan.md`,
> `review.md`, worktree diff, `abc123..def456`. Friends: … You can say
> “cancel”, “changes only”, “review only”, “plan only”, or change mode/profile.

This preflight is descriptive and reversible. It states when automatic
combining chose the newest candidate or when the run is a recorded downgrade.
It never implies that the friends independently verified a source they could
not read.

## Failure behavior

- No artifact and no unambiguous session chain: ask for an artifact or context
  choice; do not materialize a guessed diff.
- A missing, unreadable, or changed source while composing: stop before
  `afriend run` and identify the source.
- A repository snapshot refusal: retain the composite as document scope and
  state that the requested implementation evidence was not available; do not
  call the run a validation of the code.
- A friend access failure: preserve the existing `not assessed — judge access
  failure` result rather than discarding the underlying claim or source.

## Verification

Tests cover candidate discovery, precedence, ambiguity handling, composite
manifest hashing, one-repository grouping, preflight wording, and the exact
CLI invocation. End-to-end fixtures cover a prior code review plus multiple
change members, and a plan plus review plus change set. Documentation tests
keep the skill, README, and architecture diagram consistent with this behavior.
