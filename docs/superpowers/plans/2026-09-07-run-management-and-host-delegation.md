# Run management and host delegation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retained-run inventory, guarded pruning, transcript-safe status triage, durable claim-linked proposals, and accurate host-delegation guidance.

**Architecture:** A root-bounded management command owns list/prune operations. Status projects only canonical ledger metadata and safe artifact paths. The durable proposal reads that projection and exclusively creates `PLAN.md`; it never changes claims or repository contents. Canonical skill assets hold host authority guidance and are synchronized into the plugin.

**Tech Stack:** Python standard library, argparse, existing secure I/O and run-store contracts, pytest, Markdown, PlantUML.

---

### Task 1: Root-bounded inventory and deletion selection

**Files:**
- Create: `src/afriend/commands/runs.py`
- Create: `tests/test_runs.py`
- Modify: `src/afriend/cliargs.py`, `src/afriend/cli.py`

- [ ] **Step 1: Write the failing contracts**

```python
def test_list_only_reports_valid_direct_child_runs(tmp_path, capsys):
    root = tmp_path / "runs"
    _terminal_run(root, "done")
    (root / "not-a-run").mkdir(parents=True)
    assert main(["runs", "list", "--out", str(root)]) == 0
    assert "done" in capsys.readouterr().out

def test_prune_is_a_preview_until_confirmed(tmp_path):
    root = tmp_path / "runs"
    _terminal_run(root, "old", finished_at="2000-01-01T00:00:00Z")
    assert main(["runs", "prune", "--older-than", "1", "--out", str(root)]) == 0
    assert (root / "old").exists()
    assert main(["runs", "prune", "--older-than", "1", "--confirm", "--out", str(root)]) == 0
    assert not (root / "old").exists()
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_runs.py -q`

Expected: FAIL because `runs` is not registered.

- [ ] **Step 3: Implement list/prune and register it**

Create an inventory record containing run id, path, state, mode, scope, timestamp, and report path. Use secure root-anchored directory traversal only. Register `afriend runs list [--out PATH] [--json]` and `afriend runs prune --older-than DAYS [--out PATH] [--json] [--confirm]`; absent `--confirm` is always a preview. Reject negative ages. Candidate selection requires terminal metadata and excludes live, halted, malformed, locked, symlink, and non-run entries.

- [ ] **Step 4: Add refusal tests**

```python
def test_prune_never_selects_live_locked_or_symlink_entries(tmp_path):
    root = tmp_path / "runs"
    _live_run(root, "live")
    _terminal_run(root, "locked", locked=True)
    (root / "escape").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert prune_candidates(root, older_than_days=0) == []
```

Cover malformed metadata, absent roots, JSON output, and direct-child containment.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_runs.py tests/test_cliargs.py -q`

Expected: PASS.

Commit: `git add src/afriend/commands/runs.py src/afriend/cliargs.py src/afriend/cli.py tests/test_runs.py tests/test_cliargs.py && git commit -m "feat: add retained run inventory and guarded pruning"`

### Task 2: Transcript-safe status triage

**Files:**
- Modify: `src/afriend/commands/status.py`, `tests/test_status.py`

- [ ] **Step 1: Write the failing triage contract**

```python
def test_triage_links_final_claims_without_transcript_text(tmp_path):
    run = _run_with_claim(tmp_path, claim="secret raw completion must not appear")
    summary = summarize(run, root=tmp_path)
    assert summary["triage"]["unresolved_claim_ids"] == ["c-0001@1"]
    assert summary["triage"]["report_path"].endswith("report.md")
    assert "secret raw completion" not in json.dumps(summary)
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_status.py -q`

Expected: FAIL because `triage` is absent.

- [ ] **Step 3: Implement a safe projection**

Add a `triage` object to `summarize`: final claim IDs, severities/statuses, unresolved count, and safe report/ledger/evidence paths. Build it only from ledger records and known paths. Never read or render `.raw`, `.prompt`, `.err`, or transcript contents. Render a compact final-findings section after claim counts; unknown older-run data stays unknown.

- [ ] **Step 4: Add compatibility/redaction tests**

Test resolved and empty claims, missing reports, event-only run, JSON/text rendering, and a sentinel raw file that must never appear in output.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_status.py -q`

Expected: PASS.

Commit: `git add src/afriend/commands/status.py tests/test_status.py && git commit -m "feat: add transcript-safe status triage"`

### Task 3: Durable, non-mutating claim-linked proposal

**Files:**
- Create: `src/afriend/commands/plan.py`, `tests/test_plan.py`
- Modify: `src/afriend/cliargs.py`, `src/afriend/cli.py`

- [ ] **Step 1: Write the failing plan contracts**

```python
def test_plan_writes_claim_linked_proposal_without_mutating_ledger(tmp_path):
    run, before = _finished_run_with_unresolved_claim(tmp_path)
    assert main(["plan", run.name, "--out", str(tmp_path)]) == 0
    proposal = (run / "PLAN.md").read_text(encoding="utf-8")
    assert "c-0001@1" in proposal
    assert "Proposal — review before implementation" in proposal
    assert (run / "claims.jsonl").read_bytes() == before

def test_plan_refuses_existing_file(tmp_path):
    run, _ = _finished_run_with_unresolved_claim(tmp_path)
    (run / "PLAN.md").write_text("preserve", encoding="utf-8")
    assert main(["plan", run.name, "--out", str(tmp_path)]) == 2
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_plan.py -q`

Expected: FAIL because `plan` is not registered.

- [ ] **Step 3: Implement exclusive durable creation**

Locate the run through existing root validation and render stable Markdown from `status.summarize` triage. Include source run id, disclaimer that it neither resolves claims nor verifies fixes, claim-linked checklist, report path, and ledger path. Require terminal run state. Exclusively create `PLAN.md` through secure I/O; refuse existing regular files, symlinks, malformed state, and out-of-root paths. No repository writes, dispatch, or claim mutations.

- [ ] **Step 4: Add non-mutation tests**

Assert `run.json`, ledger, report, raw evidence, and a nearby repository file are byte-identical after success. Cover zero unresolved claims, malformed ledger, overwrite refusal, and deterministic ordering.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_plan.py tests/test_status.py tests/test_cliargs.py -q`

Expected: PASS.

Commit: `git add src/afriend/commands/plan.py src/afriend/cliargs.py src/afriend/cli.py tests/test_plan.py tests/test_cliargs.py && git commit -m "feat: write durable claim-linked run proposals"`

### Task 4: Canonical host-delegation guidance and documentation

**Files:**
- Modify: `src/afriend/assets/entrypoints/afriend/SKILL.md`, `src/afriend/assets/entrypoints/review/SKILL.md`
- Modify: `README.md`, `docs/README.md`, `docs/architecture/run-flow.puml`
- Regenerate: `plugins/afriend/skills/`, diagrams, diagram manifest
- Modify: documentation contract tests

- [ ] **Step 1: Write failing documentation assertions**

```python
def test_host_guidance_preserves_authority_boundary():
    router = _asset("entrypoints/afriend/SKILL.md").read_text(encoding="utf-8")
    assert "does not grant the host authority" in router
    assert "return a diff and test results" in router
    assert "Do not commit, push, or merge" in router
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_*docs*.py -q`

Expected: FAIL because the new guidance and commands are undocumented.

- [ ] **Step 3: Implement docs and assets**

Document `runs list`, confirmed `runs prune`, triage, and durable `plan`. Add two host prompts: a read-only evidence worker, and an isolated implementation worker that returns a diff/tests and does not commit/push/merge. State that host permission classification is independent of afriend, and `--allow-external-tools` grants provider-managed tools only. Update run-flow and current docs without migration language.

- [ ] **Step 4: Synchronize projections**

Run: `make plugin-sync-copy && make diagrams`

Expected: plugin and diagram outputs match their canonical source.

- [ ] **Step 5: Verify and commit**

Run: `make plugin-sync && uv run pytest tests/test_*docs*.py -q`

Expected: PASS.

Commit: `git add src/afriend/assets README.md docs plugins/afriend/skills tests && git commit -m "docs: explain run management and host delegation"`

### Task 5: Complete integration verification

**Files:** all above.

- [ ] **Step 1: Run focused regression**

Run: `uv run pytest tests/test_runs.py tests/test_plan.py tests/test_status.py tests/test_cliargs.py tests/test_*docs*.py -q`

Expected: PASS.

- [ ] **Step 2: Run portable quality gates**

Run: `make quality`

Expected: all formatting, lint, type, package, synchronization, and test gates PASS.

- [ ] **Step 3: Inspect change integrity**

Run: `git diff main...HEAD --check && git status --short && git log --oneline main..HEAD`

Expected: no whitespace errors, unintended files, or uncommitted source changes.

## Self-review

- Tasks 1–4 each implement a design requirement and have a focused test gate.
- Prune remains retain-all by default, needs age + explicit confirmation, and never selects unsafe entries.
- Triage/plan are transcript-safe and plan does not mutate review state or repository code.
- Canonical skill assets, plugin projection, docs, and diagrams are synchronized in Task 4.
