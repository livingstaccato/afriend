# Handoff — live evals for afriend (2026-09-12)

## Problem / request

A "paid" eval of afriend against real models, in three parts:

1. **Claude host eval** — does Claude Code select the right afriend skill for
   each of the 18 activation cases (`plugins/afriend/evals/`)?
2. **Codex host eval** — the same 18 cases through Codex, 2 runs per case,
   report kept local.
3. **Live friend eval** — do the friends find real defects? Crossexam spec v2,
   1 run, codex + agy + a fresh claude worker, external tools for agy only.
   Scorer selectable 1–3 (LLM judge + spot-check / hand mapping / keyword
   heuristic), three classes (matched / new-plausible / noise), folded-in
   backlog items counted and reported separately.

Follow-ups asked for in the same session: say whether docs and diagrams are
current and part of the build, then (1) point contributors at the evals from
README, AGENTS.md and the docs index, (2) give each live eval a manual `make`
target kept out of `quality`, (3) fix the CI comment that still said 500 lines.

## Changes requested and completed

| Commit | What |
| --- | --- |
| `df3de47` | Eval checker pinned to real `claude plugin eval` output |
| `cce2a7c` | `scripts/run_codex_skill_eval.py`: replay the suite through `codex exec --json` |
| `04d5a49` | `scripts/friend_eval.py` + `evals/friends/` (ground truth, provenance, scorer 1–3) |
| `945ecd2` | Docs: the host-side Codex guard detects a breach but cannot contain one |
| `f6c6612` | Codex eval moved into a container holding no other model CLI (`evals/codex/Dockerfile`) |
| `4ee081f` | Breach judged by what the container holds before/after, not by command text |
| `7df9325` | `make eval-*` targets; README / AGENTS.md / docs index pointers; CI comment 777 |

All on `origin/main`, CI green on every one (latest run 34723493784, Python
3.11 / 3.12 / 3.13). Tree clean.

Separate work landed on `main` during this session and is not covered here:
`937470e` ("feat: run afriend on Windows, dispatching claude, codex, and agy").
This handoff was rebased onto it.

## Results

- **Claude host eval:** 18 cases × 2 runs, every case 100%, `EVAL_EXIT=0`,
  $6.63.
- **Codex host eval (container):** 36/36 correct skill selection. Re-judged
  under the attempts/breach rules: 36 ok, 26 attempts to run a model CLI, 0
  breaches (none was installed before or appeared after any run).
- **Friend eval:** two real crossexam runs, recorded as fixtures in
  `tests/fixtures/friend_eval_run_real/`. Method 3 (heuristic):
  - `three-friends`: 16 claims — matched 4, new-plausible 7, noise 5; review
    recall 3 of 21 (H1, M11, L14); folded-in 0 of 13.
  - `codex-agy-superseded`: 8 claims — all new-plausible; recall 0 of 21.
  - Against a hand mapping of both runs the heuristic labelled 19 of 24
    acceptably and matched none wrongly (it misses; it does not invent).
    Treat method 3 as a smoke test, not a measurement.
  - Both runs exited 1 (`run incomplete`: crossexam left claims undecided),
    which is expected and still scorable.

## Reasoning for the approach

- **Codex in a container.** The first host run hid model CLIs by moving HOME
  and stripping PATH. Codex runs commands in a login shell, found `afriend` in
  `~/.local/bin` by absolute path, and ran read-only subcommands. Nothing was
  written, but hiding is not isolation, a separate macOS account is not either
  (`/Users/tim` is group-readable), and Codex 0.154 rejects
  `approval_policy="untrusted"`. The container holds Codex and nothing else
  that can call a model, runs `--read-only --cap-drop ALL
  --security-opt no-new-privileges`, and mounts only its own login volume.
  bwrap cannot run inside Docker, so Codex uses
  `--dangerously-bypass-approvals-and-sandbox` — the container is the sandbox.
- **Plugin streamed as a tar**, because Colima does not share `/Users/tim/code`
  and a bind mount showed a stale directory.
- **Breach = container state, not command text.** Text matching flagged a
  short-circuited `command -v afriend && afriend doctor` that never ran. The
  script now checks for model CLIs before Codex (exit 97) and after (exit 98);
  command text only records attempts. Known gap: a binary installed, used and
  deleted within one run is not caught.
- **Skill selection for Codex** = first read of
  `plugins/cache/afriend-local/afriend/<ver>/skills/<name>/SKILL.md`; Codex has
  no Skill tool event.
- **Friend eval artifact** is rebuilt from `8d82922` and digest-checked, and
  refused inside a git worktree: in this checkout the friends would get
  repository scope and could read revision 3, which holds the answers.
- **Live evals stay manual.** They are real model calls on personal logins, so
  no `eval-*` target is a prerequisite of `quality`/`check`, and CI runs none.
  `tests/test_eval_make_targets.py` pins that.

## Environment state left behind

- Docker image `afriend-codex-eval:0.154.0` and volume
  `afriend-codex-eval-home` (the eval's own Codex login) exist in Colima.
  Rebuild the image when `CODEX_VERSION` in `run_codex_skill_eval.py` changes.
- Eval outputs (Claude report.html, Codex run dirs, friend runs) were in the
  session scratchpad only; the durable record is the fixtures above.

## Checklist for next session

- [ ] **User:** approve the v0.11.1 PyPI publish — Release run 34678235648 in
      `livingstaccato/afriend` is still `waiting` on the environment approval.
- [ ] **User:** file the two PlantUML drafts as separate upstream issues and
      cross-link them:
      `.provide/plantuml-1.2026.7-regression-issue.md`,
      `.provide/plantuml-style-one-line-class-dropped-issue.md`.
- [ ] Optional: score a friend run with method 1 (`friend_eval.py judge`, set
      the spot-check `null`s by hand) or method 2 (`template`, label by hand) for
      a real measurement; method 3 under-counts matches.
- [ ] Optional: after any live friend run, check friend transcripts for reads
      of this repository before trusting a score (a friend that is not OS-confined
      can still read outside its declared scope).
- [ ] Optional: decide whether the Codex eval should also catch
      install-use-delete of a model CLI within one run (currently documented as
      a gap in `plugins/afriend/evals/README.md`).
- [ ] Not requested, not done: an Unreleased section in the changelog (the
      changelog is written only at release time).

Commands:

```bash
make eval-claude                    # Claude Code skill selection
make eval-codex-build eval-codex-login   # once
make eval-codex                     # Codex skill selection, in its container
make eval-friends                   # crossexam spec v2 (outside the repo)
make eval-friends-score FRIEND_EVAL_METHOD=3
```
