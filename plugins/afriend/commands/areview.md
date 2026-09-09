---
description: Cross-examine an artifact with agent CLIs (alias for $afriend:review)
argument-hint: [artifact-path]
disable-model-invocation: true
---

Invoke the `afriend:review` skill and give it these arguments verbatim:

$ARGUMENTS

`/areview` is a typing shortcut for `$afriend:review` and nothing more. Every
rule that governs a review — what counts as an authoritative artifact, how a
composed review context is resolved, which profile applies, that a Codex host
self-review is advisory, and that external-tool authority is never inferred —
lives in that skill. Follow it as written. Do not act on a restatement of it
from here, because there isn't one: duplicating those rules in an alias is how
the alias and the skill start disagreeing.
