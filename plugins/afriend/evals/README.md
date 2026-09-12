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
frontmatter, so the same cases are replayed through `codex exec --json`:

```bash
scripts/run_codex_skill_eval.py --dry-run            # print the plan, call nothing
scripts/run_codex_skill_eval.py --runs 2             # all 18 cases, twice each
scripts/run_codex_skill_eval.py --tag narrow --runs 1
```

Each run is a real Codex call on your subscription, against the afriend plugin
installed in `CODEX_HOME` (`afriend-local`), not this checkout: reinstall the
plugin before measuring a frontmatter change.

Codex has no Skill tool event. It selects a skill by reading its `SKILL.md`
from the plugin cache, so the first afriend `skills/<name>/SKILL.md` a run
reads is its selection, and a `no-activation` case must read none. Positive
cases use the same `expectations.json`.

**Do not run it yet.** On its first full run (2026-09-12), a `configure` case
read the user's name from `CODEX_HOME`'s path, found the installed `afriend` in
`~/.local/bin`, and ran it by absolute path: `profiles list`, `context show`,
`providers list`, a guided-setup preview, and a `doctor` that the read-only
sandbox stopped before it probed anything. Nothing was written. Hiding the CLIs
from PATH and HOME cannot stop an absolute path, and Codex 0.154 no longer
accepts the approval policy that would have refused it. The runner caught the
breach and marked the run untrusted, but catching it is not preventing it.
Containment needs Codex running where no model CLI is installed at all, and
that change is not in yet; until it is, the guard below detects and does not
contain.

The prompts ask for real work -- `afriend resume run-123` -- so each run is
checked rather than trusted:

- `-s read-only` and `--ephemeral`.
- `HOME` is an empty directory per run. Codex runs commands through your login
  shell, whose profile restores `~/.local/bin`; stripping PATH alone let a run
  execute the installed `afriend`. A pre-check refuses to start, before any
  model call, while a guarded login shell can still find `afriend`, `agy`,
  `claude` or `opencode`.
- Every MCP server in `CODEX_HOME/config.toml` is disabled with `-c`, because
  MCP tools run outside the shell sandbox. Servers a bundled plugin provides
  (the ChatGPT app's computer-use REPL) ignore that and still start, so any
  event item outside `agent_message`, `reasoning`, `command_execution` and
  `todo_list` makes the run untrusted.
- A command that invokes a model CLI is a breach unless the shell reported it
  not found. A model that tries `afriend status` and gets "command not found"
  is recorded as blocked; the runner does not pretend the attempt did not
  happen.

Exit codes follow the Claude checker, except that an untrusted run -- a
breach, an unexpected item, a run that did not complete -- exits 2 even when
another run chose wrongly, because a run that escaped its guard says nothing
reliable about selection. Results and each run's event stream are kept under
`--out` (default: a new temp directory). `tests/test_codex_skill_eval.py`
checks all of this against two real guarded runs and a fake `codex`, with no
model call.

`evals/evals.json` at the repository root is a different thing: a fixture the
pytest suite checks for internal consistency. It never runs a model. These
cases were derived from its activation-boundary prompts.
