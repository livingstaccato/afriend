# Model Selection Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each friend’s requested model and the authority for that choice
before dispatch, preserve it in the run report and metadata, document the
behavior for every provider, and publish it with the pending installation
troubleshooting guide as afriend 0.7.1.

**Architecture:** Keep command construction unchanged by adding a bounded,
immutable provenance field to the resolved `FriendSpec`. Resolve the source
once in `commands/friends.py`, then use the frozen roster for startup progress,
per-friend result rows, resume, and report rendering. Do not put model data in
the intentionally minimal lifecycle-event schema.

**Tech Stack:** Python 3.11+ standard library, dataclasses, argparse, pytest,
PlantUML, existing package/plugin projection and release workflow.

---

### Task 1: Preserve model-selection source in the resolved roster

**Files:**

- Modify: `src/afriend/adapters.py:183-196`
- Modify: `src/afriend/commands/friends.py:30-310`
- Modify: `src/afriend/roster.py:98-220`
- Modify: `src/afriend/commands/runmeta.py:299-365`
- Modify: `tests/test_explicit_friend_preflight.py`
- Modify: `tests/test_run_end_to_end_roster.py`
- Modify: `tests/test_runmeta_migration.py`
- Create: `tests/test_model_selection.py`

- [ ] **Step 1: Write failing provenance tests.**

Add `tests/test_model_selection.py` with fixtures that resolve a fake registry
and assert the frozen `FriendSpec.model_source` for every winning layer:

```python
assert resolved.specs[0].model == "invocation-model"
assert resolved.specs[0].model_source == "invocation"

assert explicit.specs[0].model_source == "explicit-friend"
assert roster.specs[0].model_source == "roster"
assert configured.specs[0].model_source == "provider-setting"
assert defaulted.specs[0].model is None
assert defaulted.specs[0].model_source == "cli-default"
```

Cover an auto-discovered provider with a static adapter model separately as
`adapter-default`. Assert that a global `--model` beats all lower layers, and
that capacity filtering, effort filling, host-role marking, and resume do not
alter the source.

- [ ] **Step 2: Run the focused tests and confirm they fail.**

Run: `uv run pytest tests/test_model_selection.py tests/test_explicit_friend_preflight.py tests/test_run_end_to_end_roster.py -q`

Expected: FAIL because `FriendSpec` does not expose `model_source` and no
provenance is resolved.

- [ ] **Step 3: Add the compatible provenance field and resolver helpers.**

In `adapters.py`, extend the frozen dataclass after its existing defaulted
fields so existing keyword and positional construction remain valid:

```python
model_source: str = "cli-default"
```

In `commands/friends.py`, define the closed source vocabulary and one helper
which chooses both the value and its source without using truthiness for model
names. Use it when resolving explicit friends and annotate the auto/roster
paths after readiness has supplied any adapter default. The exact order is:

```python
if args.model is not None:
    return args.model, "invocation"
if explicit_model is not None:
    return explicit_model, explicit_source
if provider_model is not None:
    return provider_model, "provider-setting"
if adapter_model is not None:
    return adapter_model, "adapter-default"
return None, "cli-default"
```

Pass an explicit source with roster entries (`"roster"`) and `--friend`
entries (`"explicit-friend"`). Preserve `model_source` whenever a later
`replace(...)` adjusts scope, effort, host role, or timeout. Validate a
In `commands/runmeta.py`, validate `model_source` when it is present. A
resumed roster’s source must belong to the closed set; a stored roster missing the
field receives `"cli-default"` only when its model is null and
`"recorded-unknown"` when it is non-null. Render the latter as “recorded
model; selection source unavailable,” so prior data is never falsely
attributed to a current provider setting.

- [ ] **Step 4: Run the focused tests and commit the roster contract.**

Run: `uv run pytest tests/test_model_selection.py tests/test_explicit_friend_preflight.py tests/test_run_end_to_end_roster.py -q`

Expected: PASS.

```bash
git add src/afriend/adapters.py src/afriend/commands/friends.py src/afriend/roster.py src/afriend/commands/runmeta.py \
  tests/test_model_selection.py tests/test_explicit_friend_preflight.py tests/test_run_end_to_end_roster.py tests/test_runmeta_migration.py
git commit -m "feat: record model selection provenance"
```

### Task 2: Make the selected model visible before dispatch and in audit output

**Files:**

- Modify: `src/afriend/progress.py:110-180`
- Modify: `src/afriend/commands/run.py:220-240`
- Modify: `src/afriend/rounds.py:492-575`
- Modify: `src/afriend/report.py:520-555`
- Modify: `tests/test_progress.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_run_end_to_end_basics.py`
- Modify: `tests/test_events.py`

- [ ] **Step 1: Write failing startup, metadata, report, and privacy tests.**

Specify a progress API which receives the final resolved specs before the
first call to `round_started`. Assert exactly these user-visible cases:

```text
afriend: friends ready:
afriend:   codex-security-0 (codex) -- model: gpt-6-astra [provider setting]
afriend:   opencode-architecture-0 (opencode) -- model: OpenCode CLI default (no --model passed; exact model not verified) [CLI default]
```

Assert that a no-model Codex line says `Codex CLI default`, not the caller’s
Codex configuration, and contains `exact model not verified`. Run an e2e fake
friend and assert `run.json` friends and roster contain `model_source`. Assert
the Friends table gains a `model source` column and replaces `inherited` with
the same provider-default description. Assert stdout stays only the run path.

In `tests/test_events.py`, preserve the rejection of a `model` or
`model_source` key on `run_started` and friend lifecycle events.

- [ ] **Step 2: Run the focused tests and confirm they fail.**

Run: `uv run pytest tests/test_progress.py tests/test_report.py tests/test_run_end_to_end_basics.py tests/test_events.py -q`

Expected: FAIL because no startup roster renderer exists and result rows do
not contain a source.

- [ ] **Step 3: Render provider-neutral model provenance.**

Add pure helpers in `progress.py`:

```python
def model_description(cli: str, model: str | None, source: str) -> str: ...
def model_source_label(source: str) -> str: ...
```

For a named model, render the model identifier and the stable human source
label. For no named model, render `"<Provider display name> CLI default (no
--model passed; exact model not verified)"`. Use a small display-name mapping
only for present provider names (`codex` → `Codex`, `opencode` → `OpenCode`,
`agy` → `Antigravity`, `claude` → `Claude`, `ollama` → `Ollama`); otherwise
title-case the provider identifier. Never probe the CLI or claim to know its
actual backend model.

Add `Progress.friends_ready(specs)` which emits the header and one bounded
line per frozen spec. Call it in `cmd_run` after snapshot scope reconciliation
and `reporter.run_started`, but before `_warn_doc_scope()` and every dispatch.
It remains stderr-only and emits again for a resume that will dispatch a new
round.

In `rounds.persist_result`, record `model_source` in each friend row. In
`report.py`, use the pure helpers or an equivalent dependency-free formatter
to add the `model source` column and render both new and old run metadata
truthfully. Do not modify `events.py` fields or event payloads.

- [ ] **Step 4: Run the focused tests and commit the visibility contract.**

Run: `uv run pytest tests/test_progress.py tests/test_report.py tests/test_run_end_to_end_basics.py tests/test_events.py -q`

Expected: PASS.

```bash
git add src/afriend/progress.py src/afriend/commands/run.py src/afriend/rounds.py src/afriend/report.py \
  tests/test_progress.py tests/test_report.py tests/test_run_end_to_end_basics.py tests/test_events.py
git commit -m "feat: show model selection before dispatch"
```

### Task 3: Document the model contract and synchronize plugin assets

**Files:**

- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/components.puml`
- Regenerate: `docs/architecture/components.svg`
- Modify: `src/afriend/assets/entrypoints/afriend/SKILL.md`
- Modify: `src/afriend/assets/entrypoints/configure/SKILL.md`
- Regenerate: `plugins/afriend/skills/`
- Verify existing: `docs/installation-troubleshooting.md`
- Modify: `tests/test_docs.py` only if a new tested link or heading is added

- [ ] **Step 1: Write failing documentation assertions.**

Extend the docs test to require a README statement that provider models are
shown before dispatch with their source, and that no-model means the provider
CLI default is unverified. Require `OpenCode CLI default` as the generic
example and the Codex `--ignore-user-config` nuance as a provider-specific
note. Retain the existing link to `installation-troubleshooting.md`.

- [ ] **Step 2: Run the documentation test and confirm it fails.**

Run: `uv run pytest tests/test_docs.py -q`

Expected: FAIL because the current docs omit model-selection provenance.

- [ ] **Step 3: Update live documentation and diagram source.**

In README and the router/configure skills, explain the same precedence order
as the runtime and advise `afriend providers set-model PROVIDER MODEL` for a
pinned requested model. State that `default` does not identify a backend
model. Do not add migration/renaming language.

In `components.puml`, change the roster label to
`selection, model provenance, host roles, lenses` and add a labeled arrow
from provider configuration and CLI arguments through roster resolution to
progress/report persistence. Regenerate committed rendered diagrams with:

```bash
make diagrams
make plugin-sync-copy
```

Confirm the existing troubleshooting page still distinguishes a durable Claude
marketplace checkout from the independently installed Python CLI.

- [ ] **Step 4: Run documentation/projection verification and commit.**

Run: `uv run pytest tests/test_docs.py -q && make plugin-sync-check && git diff --check`

Expected: PASS with no projection drift or whitespace errors.

```bash
git add README.md docs README.md src/afriend/assets plugins/afriend tests/test_docs.py
git commit -m "docs: explain model selection provenance"
```

### Task 4: Prepare and verify release 0.7.1

**Files:**

- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `plugins/afriend/.claude-plugin/plugin.json`
- Modify: `plugins/.claude-plugin/marketplace.json`
- Modify: `compatibility-distributions/adversarial-friends/pyproject.toml`
- Modify: `compatibility-distributions/afriends/pyproject.toml`
- Modify: `plugins/afriend/.codex-plugin/plugin.json`
- Verify: `.github/workflows/release.yml`

- [ ] **Step 1: Add the release notes and synchronized version values.**

Set the canonical version to `0.7.1`. Add an unreleased-to-`0.7.1` changelog
entry naming: requested-model/source startup visibility, truthful provider
default wording (including OpenCode), persistent report/run audit provenance,
and the Claude marketplace troubleshooting guide. Update every plugin and
compatibility package to the exact `0.7.1` version/dependency expected by the
existing version-sync gate. Do not alter package identities or repository
names.

- [ ] **Step 2: Verify version synchronization before committing.**

Run: `make version-sync-check`

Expected: PASS; every canonical package, compatibility package, plugin
manifest, and cachebuster agrees on `0.7.1`.

- [ ] **Step 3: Run full release-quality verification.**

Run: `make quality`

Expected: PASS, including format, lint, type checks, plugin sync, version
sync, wheel construction, isolated wheel installation, and the complete test
suite.

- [ ] **Step 4: Commit, merge, tag, push, and verify the public release.**

```bash
git add VERSION CHANGELOG.md plugins compatibility-distributions
git commit -m "release: prepare v0.7.1"
```

After integration to `main`, create and push the signed annotated `v0.7.1`
tag. Wait for the existing release workflow, approve the configured PyPI
environment only when it is awaiting the authorized release approval, and
verify the exact PyPI project endpoints for `afriend`,
`adversarial-friends`, and `afriends` report `0.7.1`. Verify the GitHub
release title is exactly `v0.7.1`, its workflow is successful, and its assets
are attached before announcing deployment.
