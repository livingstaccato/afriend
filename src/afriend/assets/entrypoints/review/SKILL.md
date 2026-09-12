---
name: review
description: Use for an explicit afriend review of a supplied artifact: when the user directly selects this skill ($afriend:review), for a request that names afriend ("afriend this plan", "afriend to docs/design.md"), for an operative "ask/use a friend to review ..." request, or to resume a halted run ("afriend resume <run-id>"). Do not use for generic review, challenge, poke-holes, second-opinion, or architecture requests, and not for an incidental mention of a friend.
---

# afriend review

Challenge an artifact by dispatching it to agent CLIs under distinct lenses,
then merge what they find.

The point is not more review - it is **disagreement you can see**. One model
reviewing a document tends to produce confident prose. Several models
reviewing it separately produce claims that can be compared, and the places
they disagree are usually where the real problem is.

## When this fires

Activate only for direct selection, command-like intent that starts with
`afriend` or uses `afriend to ...`, or an operative "ask/use a friend to ..."
request. An incidental mention such as "a friend sent me this" does not
activate this skill, and neither does a generic "review this", "poke holes in
this", "second opinion", or an architectural-decision request -- those stay
ordinary host work. Equivalent forms include `afriend this plan`, `afriend to this
plan`, `afriend docs/design.md`, and `afriend to docs/design.md with
crossexam`.

Sibling skills own the rest of the surface, and each is selected on its own:
`status` for provider readiness and named-run inspection, `configure` for
setup, defaults, profiles and review-context policy, `resolve` for claim
discovery and resolutions.

Phrases such as "afriend status" and "afriend review" are routing language,
not new executable aliases. The CLI command names remain `status`, `doctor`,
and `run`. Likewise, `afriend resume <run-id>` resumes the run with
`afriend run --resume <run-id>`; it belongs to this skill, is not claim
resolution, and does not need a disposition or evidence.

Conversational shorthand maps to `afriend run`; it is not a new CLI alias. If
the request names an existing path, pass that path to `afriend run`. If "this"
unambiguously refers to the current task's backing file, use that file.

An explicit supplied artifact is authoritative. Review it as a standalone
artifact with the stable command:

```bash
afriend run <artifact>
```

Use the effective `quick` profile unless the user explicitly selects a
task-only profile, a higher-cost mode, or clearly asks for its semantics.
`crossexam`, `gate`, and `loop` have added rounds and may refuse before a run
directory when the independent roster is insufficient. `afriend run <artifact>
--profile NAME` is a per-run selection; an explicit `--mode` wins over the
profile's mode.
Do not invent an artifact: use an existing path, an unambiguous task backing
file, or complete content supplied by the user; otherwise ask for a path.

## Resolve a composed review context

Context resolution belongs to the host session, not to the CLI. Collect only
host-visible explicit evidence from the selected session window. Never invent
a path or reconstruct an artifact from a bare `/code-review`
reference. The CLI composer does not read CLI session history. Ask for an
explicit source whenever the relation between evidence is unresolved.

Use `afriend context show` to inspect the persistent review-context policy.
The host may combine evidence only when review context is enabled, automatic
combining is enabled, and the selected chain is unambiguous: one explicit plan
and/or review with one repository's plural change set (a worktree diff and/or
immutable ranges). The host never combines candidates from different
repositories.

The default ambiguity policy is ask: present the eligible sources and ask the
user to choose. Under `newest`, consider same-repository candidates only and
announce the selection before composing. Under `refuse`, require an explicit
source choice. A selected artifact, or a request for changes only, review
only, or plan only, remains a standalone review rather than an automatically
combined chain.

For an approved chain, call the narrow composer with the already selected
paths and one repository root:

```bash
afriend context compose --repo <root> --out <composite> \
  --plan <plan> --review <review> --worktree-diff --range <base..head>
```

Use only the role and change flags that the approved evidence supplies. The
composer returns a deterministic, content-bound composite and its bound
sidecar manifest; it does not discover evidence, expand session visibility, or
grant authority. Its output is replaceable before `afriend run`, but a
replacement needs a matching valid bound manifest. `afriend run` freezes
run-owned artifact and manifest copies. After the host preflight, run the
returned composite with `afriend run <composite> --repo <root>`.

Read the resulting `report.md` and present its findings faithfully. Report a
recorded downgrade (including a one-friend report), a refusal, failed friends,
scope warnings, ceilings, and incomplete judging results rather than treating
them as successful independent review.

Codex is the orchestrator; its host self-review is advisory and cannot satisfy
independent-friend, judging, gate, or loop requirements. Provider selection
follows effective configured defaults. External tools are denied by default and require explicit
`--allow-external-tools=PROVIDER` or the explicit global `*` authority; never
infer that authority from provider selection or sandboxing.

When this review finishes, report the result and the next action immediately;
do not leave a completed worker as an implied queue. The host owns delegation,
edits, commits, merges, and its permission policy. `--allow-external-tools`
grants a selected friend/provider's managed tools for this review only; it
never grants the host permission to launch a worker or bypass its classifier.
For implementation, request an isolated worker that returns a diff and test
results and says: "Do not commit, push, or merge."

## Session preflight

On the first review request in a host task, ask only any unanswered setup
questions before resolving context: **Review target** (artifact, review, plan,
implementation/diffs, or comparison), **Evidence scope** (artifact only,
repository plus selected changes, or named paths), and **Judgment goal**
(report or a judging mode). Reuse the answers for ordinary follow-up work.
Before every requested new loop iteration, restate the short preflight,
because the target, scope, or policy may have changed.

### A thin roster is a question for the user, never a silent narrowing

`afriend doctor` reports effective readiness, not the roster you are allowed
to build. Before dispatch, count the qualifying workers the resolved mode
needs. If there are fewer, you must present the widening options and let the
user choose. Never quietly proceed with what happens to be ready, never
downgrade the mode on your own, and never report a readiness state as though
it settled the matter.

Each state has a documented way out, and you must name the flag, not just the
possibility:

| Reported state | What it actually means | How to widen |
| --- | --- | --- |
| `host-excluded` | the host provider is excluded **by default**, not by policy | `--friend NAME:LENS --fresh-host-worker` for an independent fresh worker, or `--include-self` for an advisory one |
| `disabled` | a user-owned persistent default, not unavailability | `--enable-provider NAME` for this run only |
| `reachable-unconfigured` | reached, but missing a required model | `afriend providers models NAME`, then `set-model`, or pass `--model` |
| `unavailable` | the executable or endpoint was genuinely absent | nothing to widen; say so plainly |
| one family ready | `cross-provider` cannot be met | several fresh same-provider workers under a task-only `--qualification-policy distinct-sessions` |

`--fresh-host-worker` is the flag that implements "a fresh Claude worker
beside Codex". It applies to explicitly named `--friend` entries from the
host's provider and makes them independent rather than advisory; they must
still disclose host-family correlation. These flags live on `afriend run`, not
on `afriend doctor`, so a `doctor` row saying `host-excluded` says nothing
about whether the run may include that provider. Do not conclude a roster is
thin from `doctor` alone.

The current harness -- you -- never qualifies as an independent friend, in any
mode, under any flag. You wrote or are about to act on the work under review
and you hold its rationale in context, which is the correlation the tool
exists to break. Offer your own read only as an explicitly advisory addition,
and only after the independent options above have been offered and declined.
A review that ends with the harness as its only substantive reviewer is
self-review, and must be reported as self-review.

Pause before dispatch and state the resolved run:

> About to start afriend to `<intent>` with plan `<plan|none>`, review
> `<review|none>`, and changes `<every selected member>`, in repository
> `<root>`. Profile/mode: `<profile>/<mode>`. Friends:
> `<name, provider, requested model, lens, role>`; qualification policy:
> `<cross-provider|distinct-sessions|distinct-models>`; downgrade: `<none|reason>`; external tools:
> `<denied|explicit grant>`.
>
> You can cancel, changes only, review only, plan only, or change the profile or mode before dispatch.

The preflight lists all selected plan, review, and change members; it never
collapses a plural change set into an unnamed "latest diff." For a standalone
artifact, name that one artifact and its normal scope in the same preflight.
Accept the resolved default, a task-only profile or mode, a task-only enabled
roster, or stop. Do not repeat the preflight for later work in the same review
session unless the user requests a new loop iteration. The preflight is
descriptive: it does not grant provider enablement, external tools,
unsafe-extra arguments, or sandbox exceptions.

As a run progresses, report when each friend finishes or fails, including its
provider, lens, result, and any downgrade. At completion, read the final
`events.jsonl` record and `report.md`, then say what finished and whether the
next action is to inspect, resolve, resume, fix configuration, retry, or start
another iteration. Do not call a failed, incomplete, downgraded, or
single-friend run a completed independent review.

## Running it

```bash
afriend run <artifact>                    # report: one parallel critique fan-out
afriend run <artifact> --mode report      # explicit spelling of the default
afriend run <artifact> --mode crossexam   # then friends judge each other
afriend run <artifact> --mode gate        # then every claim needs a resolution
afriend run <artifact> --mode loop        # repeat until nothing new appears
```

This skill drives the `afriend` console script, which comes from the
`afriend` Python package. If `afriend` is not on `PATH`, the
skill cannot run — install it with
`uv tool install git+https://github.com/livingstaccato/afriend`
(or `uv tool install .` from a checkout), then confirm with `afriend doctor`.

The CLI never runs automatically by itself. A plugin packages capabilities;
its underlying skill may be implicitly selected only by the narrow triggers
above, or directly selected by the user, and then invokes the CLI.

`<artifact>` is a path to a file — a spec, a plan, a review someone else
wrote, saved to disk. All four modes run; see `references/modes.md` for the
full rules. The effective default profile is `quick`, whose mode is `report`.
Select another mode only when the user names it or clearly requests its
semantics.

## Review context and run scope

Two supported forms select the review context:

```bash
afriend run docs/plan.md --mode report
afriend run /tmp/reviews/plan.md --repo "$PWD" --mode report
```

The first selects scope automatically only when the artifact's resolved final
target is inside the invocation repository: it gets a repository snapshot. An
in-repository symlink whose target resolves outside that repository is doc
scope only, and no repository snapshot is minted; one outside a Git repository
gets doc scope only with a warning before friends start. The second selects the
named repository explicitly; `--repo` must be that repository's Git worktree
root. It is the deliberate route for an independently frozen external
artifact together with selected repository code. `--repo` does not grant new
provider, external-tool, or write authority. Normal untracked, non-ignored
files are included in an automatic snapshot. Gitignored artifacts are
deliberately excluded from automatic Git-blob binding; use the explicit form
when they need the named repository's code context.

Every mode dispatches the artifact to every discovered friend in parallel and
writes a run directory (under `${XDG_STATE_HOME:-~/.local/state}/afriend/runs/`,
or `--out DIR`) containing `events.jsonl`, `claims.jsonl`, `report.md`,
`run.json`, a frozen `artifact/` copy, and per friend under `round-N/`:
`<friend>.prompt` (exactly
what it was asked), `.raw` (its unmodified stdout), `.err` (its stderr —
always written, even when empty), `.meta` (argv, exit code, duration,
timeout and orphan status), and `.sandbox` (the OS confinement policy it ran
under, when one was applied). By default, `afriend run` prints only the run
directory path to stdout; `--json` prints the saved run metadata instead. Read
`report.md` from the run directory and present the findings.

## Choose ready friends, not merely installed CLIs

The host is the orchestrator. In Codex, Codex remains the orchestrator and is
included as a friend by default. Its report row is labeled
`host-self-review (advisory)` with `independent=false`. It may contribute
findings and advisory verdicts, but cannot satisfy the qualifying-worker
admission rule, `--require-friends` participation, judging quorum, gate
clearance, or loop convergence. Judging modes default to two fresh workers
from different provider families; `report` may run host-only as a recorded
downgrade. A task or review profile may explicitly choose
`distinct-sessions` (two fresh workers) or `distinct-models` (two fresh
workers with different exact requested models). Neither alternative proves a
provider's backend model identity.

When a judging roster has only one qualifying worker, say so before dispatch
and offer only feasible choices, each with the flag that performs it: start
another same-provider worker (`--friend NAME:LENS` repeated, with a task-only
`--qualification-policy distinct-sessions` or `distinct-models`); start a
fresh worker from a different provider, including a fresh Claude worker beside
Codex (`--friend claude:LENS --fresh-host-worker`); enable a provider whose
persistent default is off (`--enable-provider NAME`); include the current
Claude harness as an advisory reviewer; or continue with a one-friend report
as a recorded downgrade. An option offered without its flag is not an offer
the user can act on. The current harness never qualifies. A fresh worker from
the host's provider is separate execution but must disclose host-family
correlation. A distinct-models policy accepts
only different exact requested model identifiers; a selection label such as
`fast`, `default`, or `unknown` is refused because it is not an identity, and
an accepted identifier is still not proof of the backend model that answered.

Presenting those identifiers and obtaining confirmation before dispatch is
your obligation as the host, not something the CLI enforces. `afriend run
--qualification-policy distinct-models` does not prompt, so an unattended
caller can dispatch without any confirmation ever being sought. Do not
describe that confirmation as a guarantee the tool provides.

Non-Codex hosts remain excluded by default. `--include-self` and
`--exclude-self` are mutually exclusive per-run overrides. An explicit
`--friend` roster remains a deliberate selection and may name the host or a
disabled provider, but host-role marking and independent-authority rules still
apply. Explicit friends preflight executable/endpoint availability, required
models, adapter policy, and external-tool authority before a run directory is
created.

Persistent provider defaults are user-owned, outside the reviewed repository:

```bash
afriend providers list
afriend providers enable claude
afriend providers disable opencode
afriend providers set-model ollama qwen3:8b
afriend providers clear-model ollama
afriend providers models          # every provider that can be asked
afriend providers models agy      # one of them
```

Never state what models a provider offers from memory. `providers models`
asks the installed CLI and prints what it answered; a provider whose CLI has
no listing command is reported as having none rather than guessed at, and a
model name afriend invented would fail at dispatch rather than at the point
it was suggested. Use it before recommending a model, and when a friend
fails on an exhausted quota -- a different model on that provider may hold a
separate allowance.

## Runtime depends on the run

A friend is a whole agent CLI reading a document and writing a critique.
Runtime depends on the slowest selected friend, document size, and mode;
friends within a round run in parallel. `report` is one critique fan-out.
Judging modes use three total rounds by default. `loop` permits a maximum of
five iterations by default and requires two consecutive dry rounds for
convergence.

Do not kill a run because it has gone quiet. Progress goes to **stderr**: a
line per friend as it finishes, and every 30 seconds a line naming whatever
is still outstanding and how long it has been running. If those heartbeat
lines are still appearing, the run is working. Watch stderr rather than
polling the run directory, and keep stdout clean — it carries the run path
and nothing else.

If you need an answer sooner, `--mode report` is one round instead of
several, and `--max-rounds 2` shortens a crossexam. Reducing `--timeout`
does not make friends faster; it only converts slow ones into failures.

Which mode to reach for:

* **`report`** — the default. One critique fan-out, no judging.
* **`crossexam`** — when the question is *which of these findings are real*
  rather than *what might be wrong*. Costs a fan-out per round.
* **`gate`** — when something downstream should stop until a human has
  answered each finding. This is the mode that fails a build.
* **`loop`** — when the question is *did we find everything*. It repeats
  until two consecutive rounds surface nothing new, which is the difference
  between "one round found 3 issues" and "three rounds keep finding those
  same 3 issues".

Do not reach for `gate` or `loop` on a user's behalf without saying so: both
cost several times what `report` does, and `gate` deliberately exits
non-zero until every claim is answered.

Exit codes: `0` the run reached terminal states with nothing blocked; `1` a
`gate` still has claims needing a resolution, every dispatched friend
failed, or a `crossexam` left claims undecided or lost a required friend
mid-round; `2` a usage or config error — a missing artifact, an
unrecognized `--friend` value, `--max-rounds 1` with a judging mode; `3` no
usable friend could be found, or a judging mode resolved fewer than two
independent non-host friends (install additional independent agent CLIs, or
use `report` for a host-only/single-reviewer result); `10`
`--merge orchestrator` is waiting for you to adjudicate merges (see
`references/modes.md`); `11` a judging mode stopped at a ceiling, having
neither converged nor cleared anything; `12` `--require-friends N` was set
and fewer than `N` friends produced a usable answer -- opt-in, unset by
default. A run cancelled by a signal exits `128 + signal number`.

For `loop`, naturally reaching `--max-loop-iterations` without convergence is
also a ceiling: it records that stop reason and exits `11`.

A `gate` run exits `1` while any claim still needs an answer. Discover the
unresolved claims, then resolve one at a time:

```bash
afriend resolve <run-id> --list
afriend resolve <run-id> --next
afriend resolve <run-id> --claim c-0001@1 \
    --disposition fixed|rejected|accepted-risk --evidence src/auth.py:38
```

`--evidence` must name a location, not prose. A resolution is an
attestation: the runner checks only whether that location changed since the
run started, and records `location-changed`, `location-unchanged`, or
`unverifiable`. Never present a recorded resolution to the user as proof the
defect is gone — say what was actually verified. `fixed` requires
`location-changed`; unchanged or unverifiable evidence is refused. Use
`accepted-risk` when verification is intentionally unavailable.

Check what is available first when a run comes back thin:

```bash
afriend doctor
```

It lists every known provider and its effective readiness state: `ready`,
`reachable-unconfigured`, `unavailable`, `disabled`, `host-excluded`, or
`policy-blocked`. Disabled providers are not probed. For each provider it also
reports whether schema and read-only enforcement are available and whether
effort can be verified. `doctor` exits `0` if at least one provider is ready;
it exits `3` if no provider is ready.

To inspect a named run without dispatching or changing anything, use:

```bash
afriend status <run-id-or-path>
afriend status <run-id-or-path> --watch
afriend status <run-id-or-path> --json
afriend runs list
afriend runs prune --older-than 30
afriend runs prune --older-than 30 --confirm
afriend plan <run-id-or-path>
```

`status` reports identity, mode, scope, profile, lifecycle state, friend
completion or failure, current round, claim states, downgrades, and a next
action. It includes transcript-safe final triage and links to the report,
ledger, and parsed evidence without copying captured transcript content.
`runs list` inventories audit records; retain-all is the default. `runs prune`
is preview-only without `--confirm` and never runs automatically. `plan` writes
one durable, non-mutating, claim-linked `PLAN.md` for a complete terminal run;
it is a proposal for the host to review, not a resolution or code edit. `--watch` tails new lifecycle events until the terminal event; an
unterminated final JSONL line is simply still being written. Existing runs
without `events.jsonl` remain inspectable from their saved artifacts.

## Reading the results like a reviewer, not a stenographer

The report is input to your judgment, not output to relay. Three things
deserve your attention before you hand anything to the user:

**Failed friends are not silent.** The friend table in `report.md` shows
status per friend. A run where two of three friends failed is not a clean bill
of health, and saying "no issues found" would be wrong. Say what did not run.

**Exit status lies.** Several CLIs exit 0 while producing nothing usable —
answering a different prompt, writing output to a file instead of stdout,
returning prose where JSON was asked for. The runner already treats these as
failures (see `references/troubleshooting.md`); your job is to notice when
the *pattern* suggests a misconfigured adapter rather than a quiet artifact.

**A friend that stops being dispatched has been ruled broken, not skipped.**
A downgrade saying a friend "will not be dispatched again this run" means it
failed identically twice; the runner stopped spending calls on it. Report
what it was doing wrong rather than treating the run as complete.

**A refused friend is a security refusal, not a bug.** A friend reported as
`refused: ... no OS sandbox ... available to confine it` was never started.
Its CLI does not restrain itself -- either it has no read-only mode, or its
flags were measured and none of them restricted anything -- so nothing
constrains what it reads, and an artifact under review is untrusted text that
could tell it to read anything the user can. Prefer making `sandbox-exec`
(macOS) or `bwrap` (Linux) available. A verified read-only mode is not a
substitute: it controls writes, not filesystem reads, and does not replace OS
read confinement. An adapter may declare one and still require OS confinement
-- agy declares `readonly = true` and is refused by this path, because the
sandbox is what provides its write protection. `--allow-unsandboxed-friend` is explicit risk acceptance, not a
normal fix, and lets the affected provider run without OS confinement with
same-user filesystem read access. It never weakens the provider to do so: a
flag justified only by the outer policy is dropped rather than passed, and
where the sandbox WAS the write protection the run records
`write_protected: false` and names the friend in a downgrade.

**Duplicates are under-merged on purpose.** The default merge only combines
claims with identical text and location, so two friends describing one defect
in different words appear twice. Merge them in your presentation — that is
judgment the runner deliberately declines to make.

## Reading a cross-examination

`--mode crossexam` adds a state per claim. The states are not a ranking, and
flattening them into one would throw away the thing the mode exists to
produce.

**`deadlocked` is a result, not an error.** Judges looked and disagreed. The
report quotes both sides verbatim because the runner is not entitled to pick
one — and neither are you, by default. Present the disagreement: what each
side actually argued, and what would settle it. A deadlock on a load-bearing
claim is usually the single most valuable line in the report.

**`settled-refuted` means the judges disagreed with the author, not that the
claim was noise.** It is worth one line in your summary, not silence — a
finding that two independent models rejected is still information about where
the document reads as alarming.

**`unproven` and `discarded` describe an evidence result from working
judges.** Often that is a claim citing a path or line that does not exist.
Check the claim's `evidence` field before treating it as a real defect that
nobody could confirm. A raw sandbox access failure is different: the affected
claim is **not assessed — judge access failure**, remains `incomplete`, and
does not speak to the claim's merit.

**A claim with no judges is not a passed claim.** If every friend co-authored
it, nobody independent was left to judge, and it lands `unproven`. The
downgrade list in `run.json` says when this happened.

**`budget-exhausted` invalidates the summary, not just the last round.** The
run stopped early; claims still `contested` were mid-argument, not settled.
Say the run was truncated before reporting anything as resolved.

## Choosing lenses

Each friend runs under one lens, a prose file in `lenses/` describing what to
look for and what counts as evidence. Its full text — frontmatter stripped —
is prepended to that friend's prompt, so a `security`-assigned friend is
actually asked to attack trust boundaries while an `ops`-assigned friend is
asked what happens at 3am; they are not just labeled differently after the
fact. Every friend's exact prompt is written to
`round-1/<friend>.prompt` in the run directory, so you can always check what
a given friend was actually asked. The default — no `--friend` flag at all —
is round-robin lens assignment over every discovered friend.

**`--friend cli:lens` (repeatable) does not add to or bias that default
roster — it replaces it entirely.** Any `--friend` flag switches `afriend run`
from auto-discovery to exactly the friends you listed and no others: `afriend run
spec.md --friend agy:security` runs with *one* friend, not the normal
discovered set plus a nudge toward `security`. To emphasize a lens on part
of an otherwise-normal run, list every friend you want the run to have, one
`--friend cli:lens` per friend — e.g. `--friend codex:ops --friend
agy:security --friend opencode:scope` — never a single `--friend` layered on
top of discovery. A `report` with one friend is allowed as a recorded
downgrade in `run.json` and `report.md`; present it as a single review, not a
cross-examination. `crossexam`, `gate`, and `loop` require at least two
independent non-host friends. With fewer, they refuse with exit 3 before a run
directory is created, so there is no partial judging run to interpret or
resume.

A lens name with no matching file falls back to the generic prompt alone and
is recorded as a downgrade in `run.json`, rather than failing the run or
silently pretending the friend had lens guidance.

Lenses marked `requires_failure_scenario: false` (currently only `scope`)
produce claims flagged `advisory` in `claims.jsonl` and rendered with an
`*(advisory)*` tag in `report.md` — real feedback that should never block a
decision, because "this is more than you need" is judgment rather than a
defect, and demanding a failure scenario for it would silence the lens
entirely. One thing this does *not* do yet: the claim schema still requires
every finding to include a non-empty `failure_scenario` field regardless of
lens, so a `scope`-lens friend must still supply something in that field
even though the design intends it to be optional for advisory lenses — a
known divergence, not something to paper over when you see it.

## Further reading

- `references/modes.md` — what `report`, `crossexam`, `gate`, and `loop` do,
  and which are implemented
- `references/ledger.md` — the claim/verdict/alias/resolution record types and
  how to read `claims.jsonl` directly
- `references/troubleshooting.md` — verified CLI invocation traps, what a
  failed friend usually means, and how to diagnose an empty report
