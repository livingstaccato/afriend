# Activation evals

Executable checks for the one thing `make quality` cannot verify: **which
prompts select an afriend skill, and which must select nothing.**

```bash
claude plugin eval plugins/afriend --tag no-activation --runs 1   # must not fire
claude plugin eval plugins/afriend --tag selector --ablation none --runs 1
claude plugin eval plugins/afriend --tag narrow   --ablation none --runs 1
```

Each run is a real `claude` child on your own credential and rate limit, so
the whole suite at the default 3 runs per case is ~54 agent runs. Use
`--runs 1` while iterating.

## Tags

- `no-activation` — generic requests ("review this", "poke holes", "second
  opinion", "challenge this plan", "a friend sent me this"). A passing case
  invokes **no** skill. Run these under the default ablation: the `with` and
  `without` arms should both score 1.00 with Δ 0.00, which is what shows the
  plugin did not widen activation.
- `selector` — the four direct selectors, `$afriend:review|status|configure|resolve`.
- `narrow` — command-like forms: `afriend README.md`, `afriend to <path> with
  crossexam`, `Use afriend on ...`, `Ask a friend to review ...`, and
  `afriend resume <run-id>`.

Positive cases are graded on `tool_used: Skill` alone and run with
`--ablation none`, because that grader is a `withOnly` indicator that ablation
excludes from the score. `Bash` is deliberately not granted, so a run cannot
complete the work; firing the skill is the whole contract under test.

## What this does NOT verify

`tool_used` accepts only a tool name -- `input`, `input_contains`, `args` and
`skill` are all rejected by its schema -- so the graders here prove that *an*
afriend skill fired, not *which* one. A narrow prompt that wrongly selected
`status` instead of `review` passes every grader in this directory.

That assertion now lives outside the harness, because the harness cannot
express it:

```bash
claude plugin eval plugins/afriend --ablation none --keep-temp
scripts/check_eval_skill_selection.py plugins/afriend/evals/results
```

The target is the **plugin** directory, never the suite directory below it.
`claude plugin eval plugins/afriend/evals` is accepted and resolves no plugin,
so every case runs with no afriend skill loaded: the positives all fail with
"Skill called 0x" and the negatives all pass for the wrong reason, because a
skill that cannot fire trivially satisfies "must not fire". Results then land
in `evals/evals/results/` rather than `evals/results/`, which is the visible
tell.

`expectations.json` names the skill each positive case must select. The script
reads `aggregate-result.json`, which maps each case to the `tracePath` of
every run it launched -- the only link between the two, since a kept temp
directory is `/tmp/claude-eval-<random>` and names no case -- and checks the
qualified name in those transcripts. It reads only the plugin-loaded `with`
arm; the ablation baseline runs without the plugin by design.

It passes only on complete evidence. Every case in `expectations.json` must
appear in the run, every one of its plugin-loaded runs must have kept its
trace, and every run -- not the case as a whole -- must have selected the
expected skill: under `--runs 3`, one right choice no longer excuses two wrong
ones. A wrong selection exits 1. Anything short of complete verification exits
2 and names what is missing: an expected case the run never executed, a run
whose trace was not kept, a run that loaded no plugin, results under more than
one `results/` directory (the checker will not guess which you meant), or a
result file whose shape it does not recognise. That last one is reported as a
schema mismatch rather than as advice to re-target or rerun, because the
harness changing its format is not something rerunning the eval would fix.

`tests/test_eval_skill_selection.py` exercises each of those paths against
synthetic runs, so the check is verified without any paid model call. One
fixture is real harness output: a two-run `claude plugin eval` of this suite
(Claude Code 2.1.270, result schema 1), with paths redacted and each trace cut
to its `Skill` record, so a change in the harness's result format fails a test
instead of a user. A run made without `--keep-temp` still records each
`tracePath`, pointing at a file that no longer exists -- which is what "traces
not kept" means. A checker that reports success when it found nothing to check
is the defect it exists to close -- and so is one that reports success having
checked a fraction of what it was given.

## Codex

`claude plugin eval` runs Claude Code only. Codex ships the same skills
through `plugins/afriend/.codex-plugin` and chooses between them from the same
frontmatter, so the same cases are replayed through `codex exec --json`, in a
container:

```bash
scripts/run_codex_skill_eval.py build              # once per Codex version
scripts/run_codex_skill_eval.py login              # once: the eval's own Codex login
scripts/run_codex_skill_eval.py run --dry-run      # print the plan, call nothing
scripts/run_codex_skill_eval.py run --runs 2       # all 18 cases, twice each
scripts/run_codex_skill_eval.py run --tag narrow --runs 1
```

Each run is a real Codex call on the account `login` signed in. That login is
separate from yours on the host and lives in the Docker volume
`afriend-codex-eval-home`, so the eval never reads or refreshes your
credential. The plugin under test is this checkout's --
`.agents/plugins/marketplace.json` and `plugins/afriend`, streamed in as a tar
and registered on every run -- so a frontmatter change is measured without
reinstalling anything.

Codex has no Skill tool event. It selects a skill by reading its `SKILL.md`
from the plugin cache, so the first afriend `skills/<name>/SKILL.md` a run
reads is its selection, and a `no-activation` case must read none. Positive
cases use the same `expectations.json`.

### Why a container

The prompts ask for real work -- `afriend resume run-123` -- and Codex acts on
them. The first full run (2026-09-12) ran on the host and hid the model CLIs by
moving HOME and stripping PATH. A `configure` case read the user's name from
`CODEX_HOME`'s path, found `afriend` in `~/.local/bin`, and ran it by absolute
path: `profiles list`, `context show`, `providers list`, a guided-setup
preview, and a `doctor` that the read-only sandbox stopped before it probed
anything. Nothing was written, but a hidden binary is still a binary, and Codex
0.154 no longer accepts the approval policy that would have refused it.

`evals/codex/Dockerfile` builds an image holding Codex and nothing else that
can call a model, pinned by digest and by Codex version. Each run starts a
container with a read-only root filesystem, every capability dropped,
`no-new-privileges`, a PID limit, tmpfs for home and `/tmp`, and one mount: the
login volume. No host directory is mounted. Codex's own sandbox needs user
namespaces a container does not grant, so Codex runs with that sandbox off and
the container is the boundary.

Detection stays as a second line. Before Codex starts and again after it
finishes, the container looks for `afriend`, `agy`, `claude` or `opencode` on
its PATH and as any file or link under its writable home and `/tmp`. One found
before means a broken image; one found after is a breach. Either makes the run
untrusted, as does any event item outside `agent_message`, `reasoning`,
`command_execution` and `todo_list`.

A command that invokes a model CLI is recorded as an attempt and judged no
further. Whether a command ran cannot be read from its text: in the first
container run, `command -v afriend && afriend doctor` never reached `afriend`,
printed no "not found", and was reported as a breach. With no binary to run,
an attempt cannot be one. What the second check misses is a run that installs
a model CLI, uses it, and deletes it before Codex exits.

Exit codes follow the Claude checker, except that an untrusted run exits 2 even
when another run chose wrongly: a run that escaped its boundary says nothing
reliable about selection. `run` refuses before any model call while the image
or the login is missing. Results and each run's event stream are kept under
`--out` (default: a new temp directory). `tests/test_codex_skill_eval.py`
checks all of this against two real Codex runs and a fake `docker`, with no
model call.

`evals/evals.json` at the repository root is a different thing: a fixture the
pytest suite checks for internal consistency. It never runs a model. These
cases were derived from its activation-boundary prompts.
