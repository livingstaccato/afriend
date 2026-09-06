---
name: review
description: Use only through direct qualified selection ($afriend:review) or explicit /afriend routing for a supplied artifact. Do not use for generic review requests.
---

# afriend review

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
