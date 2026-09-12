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
claude plugin eval plugins/afriend/evals --ablation none --keep-temp
scripts/check_eval_skill_selection.py <the kept directory>
```

`expectations.json` names the skill each positive case must select, and the
script reads the kept transcripts and checks the qualified name against it.
`tests/test_eval_skill_selection.py` exercises its *rejection* path against
synthetic traces -- correct selection, wrong skill, no skill at all, and an
empty directory -- so the check is verified without any paid model call. The
empty-directory case returns 2 rather than 0 on purpose: a checker that
reports success when it found nothing to check is the defect it exists to
close.

`evals/evals.json` at the repository root is a different thing: a fixture the
pytest suite checks for internal consistency. It never runs a model. These
cases were derived from its activation-boundary prompts.
