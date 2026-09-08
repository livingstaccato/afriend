# Qualifying roster policies and dispatch setup

## Purpose

When a requested judging mode has only one ready qualifying friend, afriend
must make the available next steps intelligible.  It must distinguish useful
additional perspectives from genuinely independent evidence, let a user
select an evidence-acceptance policy explicitly, and preserve that decision in
the run record.

The first activation in a host task must also establish what is being reviewed
and what evidence friends may inspect.  The host presents a compact, accurate
preflight rather than silently choosing an unrelated diff or refusing without
explaining a viable path.

## Scope

This feature adds dispatch-setup guidance, recorded roster qualification
policies, and reporting/status disclosure.  It does not change provider
security authority, grant external tools, make the invoking host a qualifying
friend, or invent a model identity for a provider that cannot report one.

## Evidence model

Each roster entry has three separately reported properties:

| Property | Meaning |
| --- | --- |
| execution | A fresh, separately launched worker session, distinct from every other worker session in the run. |
| provider family | The provider/adapter family that produced the worker, such as `codex` or `claude`. |
| model identity | The exact configured and launch-recorded model identifier for that worker.  Labels such as `fast`, `thorough`, `default`, or `unknown` are not model identities. |

The host is always `advisory`: it may contribute findings and context but is
not a qualifying friend under any policy.  This applies even when the host is
Claude and the only independent worker is Codex.  The report must call this
out as session-correlated reasoning, not portray it as a second independent
review.

## Qualification policies

`cross-provider` is the default.  A named profile/default may select another
policy, and a dispatch setup can select a task/run-only override.  The frozen
run metadata records the requested policy, the achieved roster shape, and any
downgrade.

| Policy | Qualifying minimum | Does not qualify |
| --- | --- | --- |
| `cross-provider` | Two non-host workers from distinct provider families | Two Codex workers, regardless of model; a host reviewer |
| `distinct-sessions` | Two non-host fresh worker sessions | Reuse of a worker/session; a host reviewer |
| `distinct-models` | Two non-host fresh worker sessions with distinct, exact model identities | A missing, implicit, label-only, or `unknown` model identity; a host reviewer |

All policies require two qualifying workers for `crossexam`, `gate`, and
`loop`.  `report` remains useful with one worker and records that it is a
single-friend review.  A policy is evidence admission, not a security grant:
it cannot make a blocked provider runnable or relax sandbox/tool restrictions.

For `distinct-models`, afriend must present the exact model identifiers before
dispatch and require an affirmative selection/confirmation for each one.  A
provider default may be used only if the adapter can record its concrete model
identifier; otherwise it is eligible for reports but not to satisfy this
policy.  The user may choose different Codex or Claude model identifiers, but
the report must still disclose that the provider family is shared where it is.

## First-dispatch setup

On the first afriend activation in a host task, the router asks only for
information not already explicit in the request or stored in the task's
selected setup.  It asks these questions in order:

1. **Review target:** what should friends evaluate—supplied artifact, related
   code review, plan, implementation/diffs, or a combined comparison?
2. **Evidence scope:** artifact only; bound repository snapshot plus relevant
   diffs; or named paths/artifacts.
3. **Judgment goal:** report-only feedback, or a judging mode whose selected
   qualification policy must be met.

The router proposes a context-aware combined target when recent task context
contains a code review/plan and implementation diffs.  It names every inferred
source and says that the user may cancel or change target, scope, roster, mode,
or policy before launch.  It does not silently privilege the newest diff over
a recent code review or plan.

The selected answers become task setup for the current host task.  A user can
save them as a profile/default or override them for a later run.  A requested
new loop repeats a short preflight because its target, scope, or evidence
policy may have changed; ordinary follow-up runs use the saved task setup
unless the request is ambiguous.

## Insufficient-roster preflight

When the requested mode cannot meet its policy, afriend does not create a run
directory.  It names the ready qualifying workers, their exact models, their
provider families, and the missing requirement, then offers only feasible
options.  With a Claude host and one ready Codex worker, for example:

> One qualifying worker is ready: Codex / `gpt-6-astra`.  Current policy:
> `cross-provider`.
>
> - Start another Codex worker using an exact selected model, then use
>   `distinct-sessions` or `distinct-models` for this run.
> - Include this Claude host as an advisory reviewer.  It contributes a
>   perspective but cannot satisfy a judging policy.
> - Use both of those additions.
> - Configure a different provider.
> - Continue as a one-friend report.

The launch summary must state the actual workers, roles, models, provider
families, evidence scope, target composition, mode, and selected policy.  It
must label a same-family roster as qualified under its selected alternative
policy, never as cross-provider independent.  It also tells the user they can
cancel or change the setup before dispatch.

## Lifecycle and status

The host receives a completion event for each worker that includes its final
state and the next action.  It must not describe a completed worker as queued
work.  Status and reports show a safe roster table containing role,
qualification, provider family, exact model identity/model source, and final
worker outcome.  Raw transcripts remain durable evidence but are not rendered
by default.

## Configuration and compatibility

Existing behavior is the default: `cross-provider` requires two non-host
provider families, and a host self-review remains advisory.  Existing
single-friend reports continue to run as recorded downgrades.  The setup and
policy may be supplied by an existing named profile/default, a task-only
choice, or explicit CLI arguments; precedence follows the existing explicit
invocation over profile/default pattern.  A run never inherits a later
configuration change on resume.

## Error handling

- A requested `distinct-models` run refuses before run creation if either
  candidate lacks a concrete exact model identity or the two identities match.
- A requested second worker that is unavailable or policy-blocked remains
  unavailable; afriend does not convert policy selection into a provider tool
  grant.
- A host reviewer never turns a judging run into an eligible roster.  If no
  offered option can qualify, afriend offers a report downgrade or stops.
- A resumed run uses its frozen policy and roster facts; it may not be
  retroactively qualified by a new preference.

## Test and documentation requirements

Tests cover qualification of each policy, model-identity refusal cases,
host-advisory exclusion, fresh-session identity, configuration precedence,
insufficient-roster prompts, combined-target inference, frozen-resume
behavior, and safe report/status wording.  Documentation covers the three
policies, exact-model contract, first-dispatch questions, and examples for
Claude-hosted and Codex-hosted tasks.  Architecture diagrams are updated only
where the setup-to-roster-to-run flow changes; unrelated historical diagrams
remain unchanged.
