# Repository Review Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a repository-scoped afriend review genuinely readable by every admitted friend, and never convert a sandbox-access failure into a semantic discard.

**Architecture:** Codex’s outer OS sandbox will grant its measured global skill-root dependency read-only, in addition to its existing private Codex state path and private checkout. Adapter-declared raw stderr markers will classify known confinement failures even when a CLI exits zero; dispatch then turns the attempt into a failed judge, and the existing missing-judge path marks affected crossexam claims incomplete rather than discardable.

**Tech Stack:** Python 3.11+, stdlib dataclasses/TOML, pytest, macOS Seatbelt/bubblewrap policy generation, canonical afriend plugin assets.

---

### Task 1: Declare and prove Codex’s measured startup read dependency

**Files:**
- Modify: `tests/test_confine_optin.py`
- Modify: `src/afriend/assets/adapters/codex.toml`

- [ ] **Step 1: Write the failing adapter-contract test**

Add this test after `test_codex_opts_in_and_declares_what_it_needs`:

```python
def test_codex_confined_startup_reads_only_its_state_and_global_skill_root():
    codex = _registry()["codex"]

    assert "~/.codex" in codex.sandbox_read
    assert "~/.agents/skills" in codex.sandbox_read
    assert all(path != "~/.agents" for path in codex.sandbox_read)
    assert all(path != "~" for path in codex.sandbox_read)
```

- [ ] **Step 2: Verify the test fails for the missing dependency**

Run: `uv run pytest tests/test_confine_optin.py::test_codex_confined_startup_reads_only_its_state_and_global_skill_root -v`

Expected: FAIL because `~/.agents/skills` is absent from the Codex adapter’s `sandbox_read` declaration.

- [ ] **Step 3: Add the narrow read-only adapter allowance**

Change the Codex sandbox declaration to:

```toml
[sandbox]
os_confine = true
# Codex 0.150.1 scans this global root during an actual turn even when
# --ignore-user-config is present. It is read-only, is not the user's whole
# ~/.agents directory, and is required for a confined repository review to
# reach its checkout.
read = ["~/.codex", "~/.agents/skills"]
write = ["~/.codex"]
```

Keep the surrounding comments accurate: state that the allowance was
measured from a real Seatbelt denial and that apps/plugins remain disabled.

- [ ] **Step 4: Verify the declaration and confinement suite**

Run: `uv run pytest tests/test_confine_optin.py tests/test_sandbox.py -v`

Expected: PASS, including the existing real confinement tests on platforms
where their OS mechanism is available.

- [ ] **Step 5: Commit the focused contract change**

```bash
git add tests/test_confine_optin.py src/afriend/assets/adapters/codex.toml
git commit -m "fix: admit Codex startup skill root to review sandbox"
```

### Task 2: Classify adapter-proven sandbox access failures from raw diagnostics

**Files:**
- Modify: `src/afriend/adapters.py`
- Modify: `src/afriend/sandbox.py`
- Modify: `src/afriend/dispatch.py`
- Modify: `src/afriend/assets/adapters/codex.toml`
- Modify: `tests/test_adapters.py`
- Modify: `tests/test_dispatch_findings.py`

- [ ] **Step 1: Write failing parser and classifier tests**

Add a TOML fixture in `tests/test_adapters.py` whose adapter has:

```toml
[sandbox]
access_failure_stderr = ["provider_loader: denied read"]
```

Assert its parsed adapter exposes exactly `("provider_loader: denied read",)`.
Add a rejection test for a non-list value and for an empty marker. In
`tests/test_dispatch_findings.py`, add:

```python
def test_confined_access_diagnostic_turns_a_zero_exit_into_a_failed_review(monkeypatch, tmp_path):
    from afriend import dispatch
    from afriend.adapters import Adapter, FriendSpec
    from afriend.authority import AuthorityPolicy

    adapter = Adapter(
        name="judge",
        binary="judge",
        base_argv=[],
        prompt_mode="stdin",
        prompt_flag="",
        readonly_argv=["--readonly"],
        schema_flag="",
        model_flag="",
        internal_timeout_flag="",
        effort_kind="none",
        sandbox_confine=True,
        sandbox_access_failure_stderr=("provider_loader: denied read",),
    )
    # Replace process execution with a syntactically successful answer plus
    # the adapter-declared raw diagnostic; the model prose is not inspected.
    monkeypatch.setattr(dispatch, "run_process", lambda *args, **kwargs: SpawnResult(
        argv=["judge"], exit_code=0, stdout='{"no_findings": true}',
        stderr="provider_loader: denied read", duration_s=0.0, timed_out=False,
        result=NormalizeResult({"no_findings": True}, [], True),
        failure_reason=None, orphans_suspected=False,
    ))
    monkeypatch.setattr(dispatch.sandbox, "detect", lambda: dispatch.sandbox.BWRAP)
    monkeypatch.setattr(dispatch.sandbox, "wrap", lambda argv, *args: argv)

    _spec, _capability, outcome, _policy = dispatch._dispatch(
        FriendSpec("judge-ops-0", "judge", "ops", None, None, "repo", 5),
        tmp_path, {"judge": adapter}, None, tmp_path / "prompt", tmp_path / "schema",
        authority_policy=AuthorityPolicy.deny_all(),
    )

    assert outcome.failure_reason == "review access failure: provider_loader: denied read"
```

Import `NormalizeResult` and `SpawnResult` in that test module. The test must
fail first because neither the adapter field nor dispatch classification exists.

- [ ] **Step 2: Verify the failure is for the missing access-failure contract**

Run: `uv run pytest tests/test_adapters.py tests/test_dispatch_findings.py::test_confined_access_diagnostic_turns_a_zero_exit_into_a_failed_review -v`

Expected: FAIL with an unknown adapter field or missing `sandbox_access_failure_stderr` attribute; do not accept an unrelated test failure.

- [ ] **Step 3: Implement the generic adapter-owned marker contract**

Add this immutable field to `Adapter` next to the other sandbox fields:

```python
sandbox_access_failure_stderr: tuple[str, ...] = ()
```

In `load_adapters`, read `data.get("sandbox", {}).get("access_failure_stderr", [])`,
validate that it is a list of nonempty strings with no newline, and store it
as a tuple. Add a pure helper in `sandbox.py`:

```python
def access_failure(stderr: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in stderr:
            return marker
    return None
```

After `run_process(...)` returns in `dispatch._dispatch`, only for an
OS-confined execution, replace a successful result with a failure when the
adapter’s declared marker appears in raw stderr:

```python
marker = sandbox.access_failure(outcome.stderr, adapter.sandbox_access_failure_stderr)
if os_confined and marker is not None:
    outcome = dataclasses.replace(outcome, failure_reason=f"review access failure: {marker}")
```

Do not inspect model reasoning or invent generic permission-error matching.
The marker is adapter-owned, raw-process evidence and fails conservatively.

Declare Codex’s measured marker:

```toml
access_failure_stderr = ["codex_skills_extension::loader::host: failed to scan skill path"]
```

- [ ] **Step 4: Verify parser and dispatch behavior**

Run: `uv run pytest tests/test_adapters.py tests/test_dispatch_findings.py -v`

Expected: PASS. The focused dispatch test proves an exit-0 response with a
known sandbox denial cannot count as a usable review.

- [ ] **Step 5: Commit the failure classification**

```bash
git add src/afriend/adapters.py src/afriend/sandbox.py src/afriend/dispatch.py \
  src/afriend/assets/adapters/codex.toml tests/test_adapters.py tests/test_dispatch_findings.py
git commit -m "fix: mark sandbox-denied reviews incomplete"
```

### Task 3: Preserve access-failure claims as incomplete in crossexam

**Files:**
- Modify: `tests/test_run_end_to_end_crossexam.py`
- Modify: `src/afriend/commands/crossexam.py`

- [ ] **Step 1: Write the failing crossexam regression**

Build a two-friend fixture using the existing end-to-end helper. Make the
only eligible judge return an adapter-classified `review access failure` in
both judging rounds. Assert:

```python
assert outcome.incomplete is True
assert outcome.states[claim_id] == "incomplete"
assert "discarded" not in outcome.states.values()
assert any("not assessed" in note and "access failure" in note for note in outcome.downgrades)
```

The fixture must use a raw `SpawnResult.failure_reason`, not the judge’s
free-text verdict reasoning. This distinguishes a broken review environment
from a claim that a working judge could not verify.

- [ ] **Step 2: Verify the regression fails**

Run: `uv run pytest tests/test_run_end_to_end_crossexam.py -k access_failure -v`

Expected: FAIL because the run currently reports only that the judge did not
report; the user-facing reason is not retained per affected claim.

- [ ] **Step 3: Record the reason at the crossexam boundary**

When a result has a `failure_reason` beginning with `review access failure:`,
retain the existing `_never_reported(...)` behavior and add this bounded,
claim-specific downgrade for each claim in that judge’s pending slice:

```python
outcome.downgrades.append(
    f"round {round_no}: {claim.id} was not assessed — {spec.name} had {result.failure_reason}."
)
```

Keep the existing `any_failed` update. That makes the run incomplete and
causes `state_for(..., required_missing=True)` to return `incomplete`, which
clears/avoids the discard signature. Do not create a new verdict state or
use the model’s `unverifiable` prose as failure evidence.

- [ ] **Step 4: Verify the regression and neighboring lifecycle tests**

Run: `uv run pytest tests/test_run_end_to_end_crossexam.py tests/test_discard_consecutive.py tests/test_verdicts_lifecycle.py -v`

Expected: PASS. Existing repeated-unverifiable evidence remains discardable
only when no required judge access failure occurred.

- [ ] **Step 5: Commit the crossexam reporting change**

```bash
git add src/afriend/commands/crossexam.py tests/test_run_end_to_end_crossexam.py
git commit -m "fix: report unassessed claims after judge access failure"
```

### Task 4: Synchronize user-facing contract and distribution payload

**Files:**
- Modify: `tests/test_docs.py`
- Modify: `src/afriend/assets/entrypoints/afriend/references/modes.md`
- Modify: `src/afriend/assets/entrypoints/afriend/references/troubleshooting.md`
- Generated: `plugins/afriend/skills/`

- [ ] **Step 1: Write the documentation assertions before prose changes**

Add `test_modes_docs_distinguish_access_failure_from_discard()` to
`tests/test_docs.py` after `test_modes_docs_explain_zero_response_failure_summary_output`:

```python
def test_modes_docs_distinguish_access_failure_from_discard():
    modes = (AFRIEND / "references" / "modes.md").read_text().lower()

    assert "not assessed — judge access failure" in modes
    assert "working judges repeatedly had access to the evidence" in modes
```

`tests/test_skill_layer.py::test_runtime_assets_project_byte_for_byte_below_router_skill`
already proves the generated projection follows canonical assets; do not
duplicate the same assertion against `plugins/afriend`.

- [ ] **Step 2: Verify the assertions fail**

Run: `uv run pytest tests/test_docs.py::test_modes_docs_distinguish_access_failure_from_discard -v`

Expected: FAIL because neither phrase documents the corrected contract yet.

- [ ] **Step 3: Update canonical documentation and projection**

In `modes.md`, replace any implication that every repeated `unproven` is
discarded with the access-qualified rule. Explain that a sandbox/permission
failure is an incomplete review, blocks a gate, and says nothing about the
claim’s merit. In `troubleshooting.md`, explain that the Codex adapter’s
confined review needs its measured global skill-root read allowance, while
apps/plugins remain denied and the rest of `~/.agents` remains unavailable.

Run:

```bash
make plugin-sync-copy
make plugin-sync
```

Expected: the generated plugin projection is synchronized with canonical
assets.

- [ ] **Step 4: Verify documentation and complete portable quality**

Run: `make quality`

Expected: all portable checks, wheel/isolated-install checks, plugin sync,
and the full pytest suite pass.

- [ ] **Step 5: Commit synchronized documentation**

```bash
git add src/afriend/assets plugins/afriend tests
git commit -m "docs: explain repository review access failures"
```

### Task 5: Validate the actual Codex compatibility path and close the branch

**Files:**
- Verify only; no source edit unless the measured command reveals an
  additional, narrowly scoped startup dependency.

- [ ] **Step 1: Run the bounded real Codex read-only probe under the generated Seatbelt profile**

Use the same `childenv.build`, `sandbox.policy_for`, `sandbox.wrap`, Codex
adapter argv, and repository working directory as `dispatch._dispatch`.
The prompt must ask Codex to read a known repository file and return its
first line; it must not ask for unrelated paths or a semantic review.

- [ ] **Step 2: Verify the probe result**

Expected: exit 0, no `codex_skills_extension::loader::host: failed to scan
skill path` diagnostic, and the expected repository-file content. If it
fails, record the exact raw diagnostic and add only the next measured
read-only dependency with a red regression test; do not broaden to home or
all of `.agents`.

- [ ] **Step 3: Perform final verification**

Run:

```bash
git diff --check
make quality
git status --short
```

Expected: no whitespace errors, `make quality` passes, and no uncommitted
source or generated-payload changes remain.

- [ ] **Step 4: Commit any probe-driven correction, if one was required**

```bash
git add src/afriend tests plugins/afriend docs
git commit -m "fix: verify Codex repository review confinement"
```

Only create this commit if Step 2 required an additional code or document
change.

## Plan self-review

- **Spec coverage:** Task 1 gives the measured Codex path read-only access;
  Task 2 makes raw, adapter-owned access failures fail closed; Task 3 maps
  them to explicit incomplete/not-assessed claims; Task 4 updates canonical
  docs and the generated plugin; Task 5 performs the real review-path
  compatibility proof.
- **Placeholder scan:** No task defers a behavior, uses a generic permission
  heuristic, or grants a broad home directory.
- **Type consistency:** `Adapter.sandbox_access_failure_stderr` is parsed as
  `tuple[str, ...]`, passed to `sandbox.access_failure`, and produces the
  exact `review access failure: <marker>` string consumed by crossexam.
