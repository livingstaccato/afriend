# Context-Aware Review Implementation Plan

> **For the implementer:** Follow `superpowers:executing-plans` and implement
> this plan task by task, with the listed test command after each task.

**Goal:** Let the `/afriend:review` host skill turn an unambiguous session
chain of plan, prior review, and one repository's implementation changes into
a deterministic composite artifact. Friends then evaluate the correct
question—artifact, plan validation, review validation, or full chain—without
the CLI ever reading a chat transcript.

**Architecture:** The host is the only session-aware component. It identifies
explicit paths and command references already visible in the task, resolves
them according to a persistent review-context policy, and invokes a new CLI
composer with those exact inputs. The composer validates paths and the one
repository boundary, captures immutable source identities, writes the
composite Markdown plus sidecar manifest, and returns their paths. `afriend
run` treats that composite as a normal artifact while recording the manifest
in `run.json` for later inspection.

**Tech stack:** Python 3.11 stdlib, `argparse`, JSON session configuration,
Git CLI through the existing repository helpers, pytest, package assets synced
to the Codex and Claude plugin projections.

## Task 1: Add strict, user-owned review-context configuration

**Files:**

- Modify: `src/afriend/sessionconfig.py`
- Modify: `tests/test_sessionconfig.py`
- Modify: `src/afriend/commands/init.py`
- Modify: `tests/test_guided_init.py`

**Step 1: Write failing configuration tests.**

Add tests that prove the absent configuration resolves to:

```python
ReviewContextConfig(
    enabled=True,
    sources="current-task",
    automatic_combine=True,
    ambiguity="ask",
)
```

Also cover JSON round-trip, rejection of unknown or wrongly typed
`review_context` fields, each closed-choice validator, and an atomic update
which preserves custom profiles and `default_profile`. Extend the guided-init
tests with an `--apply` preview that lists review-context settings only when
the user explicitly chose them.

**Step 2: Run the focused tests to confirm they fail.**

Run: `uv run pytest tests/test_sessionconfig.py tests/test_guided_init.py -q`

Expected: failures because `ReviewContextConfig` and the settings do not
exist.

**Step 3: Implement the config value and update API.**

In `sessionconfig.py`:

- Add an immutable `ReviewContextConfig` dataclass and constants for the two
  allowed `sources` values and three allowed `ambiguity` values.
- Add it to `SessionConfig`, and strictly validate the nested object. Keep
  configuration parsing bounded, immutable, locked, and atomically written
  using the existing mechanisms.
- Advance the canonical configuration schema version and admit the previously
  written shapes with the default review-context policy. All new writes emit
  the complete newest shape.
- Add a narrow `set_review_context(...)` updater. It accepts only explicitly
  supplied fields, validates prospective state under the same disk-input
  contract, and retains unrelated user settings.

In `commands/init.py`, accept only explicit guided review-context selections,
include the exact settings in the no-write preview, and persist them only with
`--apply` after all selected config documents validate. Do not let guided
setup expand the host's session visibility or grant repository/provider/tool
authority.

**Step 4: Run the focused tests.**

Run: `uv run pytest tests/test_sessionconfig.py tests/test_guided_init.py -q`

Expected: PASS.

## Task 2: Build a deterministic review-context composer

**Files:**

- Create: `src/afriend/reviewcontext.py`
- Create: `tests/test_reviewcontext.py`
- Reuse when applicable: `src/afriend/snapshotgit.py`,
  `src/afriend/snapshotvalidation.py`, `src/afriend/jsonio.py`

**Step 1: Write failing pure-logic tests.**

Cover these public, side-effect-minimized operations:

- A `ContextIntent` is exactly `artifact`, `validate-plan`,
  `validate-review`, or `validate-chain`; input role combinations choose the
  most specific valid intent.
- A `ContextInput` captures role, display label, absolute source path,
  `sha256:` digest, and optional Git identity without embedding untrusted
  arbitrary metadata.
- A change set accepts multiple members: one worktree diff and zero or more
  explicit commit ranges. Its members must resolve to one exact repository
  root.
- Plan/review source files are UTF-8, regular readable files. Missing,
  unreadable, or changed-between-hash-and-read inputs refuse before output.
- Git ranges resolve to immutable endpoint commits and produce a bounded
  deterministic patch/summary. A dirty worktree is recorded by hash.
- The emitted Markdown orders inputs deterministically, includes the exact
  question, labels every evidence block, and instructs friends to say “not
  assessed” for unavailable evidence rather than treating it as refuted.
- The sidecar manifest is strict JSON and contains only reconstructible
  source identity, selected intent, repository identity, and output digest.

Use a small temporary Git repository fixture with two commits and a dirty
file. Include a three-member change set—worktree plus two ranges—to prevent a
single-diff implementation from passing.

**Step 2: Run the focused tests to confirm they fail.**

Run: `uv run pytest tests/test_reviewcontext.py -q`

Expected: test collection failure because the module does not exist.

**Step 3: Implement the pure composer.**

Create `reviewcontext.py` with:

- Frozen, validated data structures for inputs, change members, and a
  manifest.
- A small repository abstraction around existing bounded Git helpers; do not
  shell-concatenate revision expressions or make the host's chat transcript
  an input.
- `compose(...)` which validates all inputs before creating the target,
  computes stable identities, renders a canonical Markdown composite, and
  atomically writes `<output>.json` only after the composite succeeds.
- A verifier that re-reads every file/range/worktree identity immediately
  before writing; it raises a clear `UsageError` when a source changed.

The compose API receives explicit paths, `--range` expressions, and the
worktree-diff choice. It never searches session history, guesses an artifact,
or selects a repository on its own.

**Step 4: Run the focused tests.**

Run: `uv run pytest tests/test_reviewcontext.py -q`

Expected: PASS.

## Task 3: Expose composition and context settings through a narrow CLI

**Files:**

- Modify: `src/afriend/cliargs.py`
- Modify: `src/afriend/cli.py`
- Create: `src/afriend/commands/context.py`
- Create: `tests/test_context_command.py`
- Modify: `tests/test_cliargs.py`

**Step 1: Write failing CLI tests.**

Specify these stable forms:

```bash
afriend context show --json
afriend context set --sources current-task --ambiguity ask
afriend context compose --repo REPO --out COMPOSITE \
  --plan PLAN --review REVIEW --worktree-diff --range BASE..HEAD
```

Test that `show` is read-only; `set` changes only named settings; `compose`
requires `--repo`, requires at least one `--plan` or `--review` and one change
member, permits repeated `--range`, rejects cross-repository or duplicate
role sources, writes no artifact on any refusal, and prints a concise JSON
or text receipt naming the intent, composite, and manifest. Verify no command
accepts provider, external-tool, sandbox, model, or arbitrary flag settings.

**Step 2: Run the focused tests to confirm they fail.**

Run: `uv run pytest tests/test_context_command.py tests/test_cliargs.py -q`

Expected: parser and command-dispatch failures because `context` is absent.

**Step 3: Implement parser, dispatch, and command.**

- Add a `context` parser family, with required subcommands `show`, `set`, and
  `compose`.
- Make `set` use explicit boolean paired flags (`--enabled` /
  `--disabled`, `--automatic-combine` / `--no-automatic-combine`) so omitted
  fields remain untouched.
- Make `compose` pass only exact filesystem and Git arguments to
  `reviewcontext.compose`; derive intent from selected role inputs rather than
  accepting a free-form intent override.
- Add `cmd_context` to `cli.py` imports, exports, and dispatch.
- Return a nonzero usage refusal before a run directory exists whenever
  repository identity, source readability, source stability, or composition
  validation fails.

**Step 4: Run the focused tests.**

Run: `uv run pytest tests/test_context_command.py tests/test_cliargs.py -q`

Expected: PASS.

## Task 4: Preserve the composite manifest in normal run evidence

**Files:**

- Modify: `src/afriend/commands/run.py`
- Modify: `src/afriend/commands/runmeta.py`
- Modify: `src/afriend/runstore.py` if a safe sidecar-copy helper is needed
- Modify: `tests/test_run_end_to_end_basics.py`
- Modify: `tests/test_repository_scope_docs.py`
- Modify: the focused run metadata tests found by `rg "artifact_hash|run.json" tests`

**Step 1: Write failing integration tests.**

Compose a plan + review + three-member change set, run it with the fake
friend, and assert:

- The frozen artifact is the composite, and the prompt contains the selected
  intent and every evidence label.
- `run.json` records a `review_context` object containing intent, immutable
  manifest digest, and the frozen manifest path or copied manifest content.
- Repository scope is still established through the existing `--repo`
  snapshot path, not through composer metadata.
- Resume reads the frozen composite and retains its context evidence without
  rebuilding from mutable working files.
- A document-scope downgrade is described as unable to validate implementation
  evidence, not as a successful implementation validation.

**Step 2: Run the focused tests to confirm they fail.**

Run: `uv run pytest tests/test_run_end_to_end_basics.py tests/test_repository_scope_docs.py -q`

Expected: failures because run metadata ignores the sidecar manifest.

**Step 3: Implement run-time evidence capture.**

- Detect a composer-generated, strictly validated sidecar adjacent to the
  supplied composite artifact; arbitrary Markdown files remain ordinary
  artifact reviews.
- Copy the validated manifest into the run-owned artifact area with the same
  secure-copy rules as the composite, then add a bounded `review_context`
  field to `_base_meta`.
- Preserve this data in every lifecycle transition and on resume. Do not
  derive new change information on resume.
- Update reporting/scope wording so an unavailable repository snapshot is
  plainly “not assessed” for implementation validation.

**Step 4: Run the focused tests.**

Run: `uv run pytest tests/test_run_end_to_end_basics.py tests/test_repository_scope_docs.py -q`

Expected: PASS.

## Task 5: Teach the host skills to resolve context, preflight, and ask

**Files:**

- Modify: `src/afriend/assets/entrypoints/review/SKILL.md`
- Modify: `src/afriend/assets/entrypoints/afriend/SKILL.md`
- Modify: `src/afriend/assets/entrypoints/configure/SKILL.md`
- Modify: `tests/test_skill_layer.py`
- Modify: `README.md` and the relevant files under `docs/`
- Modify: architecture diagrams only where they depict the host-to-CLI review
  path

**Step 1: Write failing documentation/skill tests.**

Extend `test_skill_layer.py` and documentation tests so they require:

- explicit artifacts remain authoritative;
- the host may combine an unambiguous chain only when review-context is
  enabled and automatic combining is enabled;
- default ambiguity asks rather than silently choosing unrelated content;
- `newest` is limited to same-repository candidates and reports the choice;
- composed review wording names the plan/review and plural change members;
- users can say cancel, changes only, review only, plan only, or select a
  profile/mode before dispatch;
- context settings are inspectable/changeable through `afriend context`,
  with examples that do not imply new authority.

**Step 2: Run the focused tests to confirm they fail.**

Run: `uv run pytest tests/test_skill_layer.py tests/test_docs.py -q`

Expected: assertions fail because the existing review skill requires one
exact artifact and has no context policy.

**Step 3: Update canonical assets and docs.**

In the focused `review` skill, direct the host to:

1. collect only explicit host-visible evidence candidates under the selected
   session window;
2. apply the configured precedence/ambiguity policy;
3. invoke `afriend context compose` for an approved unambiguous validation
   chain;
4. give the exact preflight with intent, all named evidence, repository,
   profile/mode, roster, and cancellation/override options; and
5. invoke `afriend run <composite> --repo <root>` only after that preflight.

Keep standalone-review behavior as the fallback when a user selects one
artifact or asks for review-only/plan-only/changes-only. The skills must not
invent a path after a bare `/code-review` reference and must ask when the
relation is unresolved. Update the router and configure skill to route and
explain `afriend context show/set`, then update README and architecture
documentation to show the host-session resolver, CLI composer, immutable
manifest, and normal run snapshot as one path.

Run `make plugin-sync-copy` after editing canonical assets; never hand-edit
the projection under `plugins/afriend/skills/`.

**Step 4: Run the focused tests.**

Run: `uv run pytest tests/test_skill_layer.py tests/test_docs.py -q && make plugin-sync-check`

Expected: PASS.

## Task 6: End-to-end verification and adversarial regression coverage

**Files:**

- Modify/add: the narrow tests above only as gaps are discovered
- Modify: `CHANGELOG.md` if the repository uses it for unreleased changes

**Step 1: Add end-to-end behavioral coverage.**

Add a test at the skill/CLI seam that drives this exact sequence:

1. a known plan and code-review artifact;
2. multiple implementation changes in the same temporary repository;
3. host composition receipt and preflight;
4. normal `afriend run` with a repository snapshot; and
5. report/run metadata inspection.

Assert that the review question is chain validation—not merely “review the
latest diff”—and that each source can be traced from report metadata back to
its immutable identity. Add boundary cases for ambiguous two-review chains,
cross-repository work, and stale source hashes, all refusing before dispatch.

**Step 2: Run quality gates.**

Run:

```bash
make format-check
make lint
make typecheck
make plugin-sync-check
make test
make quality
```

Expected: every portable check passes. If a check finds a defect, fix it in
the owning task above, add a regression test, and rerun that task’s focused
command before restarting the quality sequence.

**Step 3: Inspect the final diff and documentation consistency.**

Run:

```bash
git diff --check
git status --short
rg -n "context compose|automatic combine|validate-chain|review_context" README.md docs src/afriend/assets plugins/afriend/skills
```

Expected: no whitespace errors; canonical and projected skill language agree;
all docs describe the shipped behavior in present tense; no obsolete behavior
or migration guidance remains.
