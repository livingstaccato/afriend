# Friend eval

The activation evals in `plugins/afriend/evals/` ask whether a host selects
the right afriend skill. This one asks whether the friends find real defects.

It replays a review that already happened. Revision 2 of
`docs/superpowers/specs/2026-08-22-adversarial-friends-design.md` was reviewed
by independent friends, and revision 3's section 19 records every finding and
how it was settled. `ground-truth.json` is that record: 21 review findings, and
13 items of v2's own backlog that v3 folded in. `provenance.json` names the
commit and digest of revision 2.

## Running it

```bash
scripts/friend_eval.py artifact --out /tmp/friend-eval/spec-v2.md
# run the afriend command it prints: crossexam, codex + agy + a fresh claude worker
scripts/friend_eval.py score /tmp/friend-eval/runs --method 3
```

The artifact is rebuilt from git history and checked against the recorded
digest, so a shallow clone cannot produce it (`git fetch --unshallow`). It must
be written outside any git repository: inside this checkout the friends get
repository scope, and the repository holds revision 3 -- the answers. The
command refuses a path inside a worktree.

A friend that is not OS-confined can still read outside its declared scope.
After a run, check its transcripts for reads of this repository before trusting
the score.

The run is several real model calls on each provider's own credential.

## Scoring

Every claim lands in one class:

| class | meaning |
| --- | --- |
| matched | names a ground-truth finding; two claims naming one finding are both matched, and the finding is recalled once |
| new-plausible | names no known finding, and is worth a person's look |
| noise | names no known finding, and is not |

Recall is reported separately for review findings and folded-in items. No
reviewer raised the folded-in backlog, so count it in or out as the question
requires. A claim the run superseded is scored through its successor.

`--method` chooses who labels the claims:

1. **An LLM judge.** `judge <run> --judge-cmd CMD --out mapping.json` sends the
   ground truth and every claim to `CMD` on stdin and saves the JSON it returns,
   with a seeded sample of claims (`--spot-check`, default 3) set to `null`.
   Set each to `true` or `false` after reading the claim yourself.
   `score --method 1 --mapping mapping.json` refuses while any is `null`, and
   exits 1 when any is `false`: a judge caught wrong is not a score.
2. **A person.** `template <run> --out mapping.json` writes every claim with an
   empty label; `score --method 2 --mapping mapping.json` refuses until each has
   one.
3. **A keyword heuristic**, computed by `score --method 3`. A claim's text and
   location match the finding whose keywords they share most, if they share at
   least half; an unmatched claim is noise exactly when the run discarded or
   refuted it. Against a hand mapping of the two recorded runs it labelled 19
   of 24 claims acceptably and matched none wrongly -- by missing five. Treat it
   as a smoke test, not a measurement.

A mapping that misses a claim, invents one, or names an unknown finding is
refused (exit 2) with every problem listed at once.

`tests/test_friend_eval.py` checks all of this against two real crossexam runs
of the artifact (claims and final states only) and a fake judge, without a
model call.
