# Qualifying Roster and Dispatch Setup Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Let afriend explicitly qualify same-provider worker rosters under a selected evidence policy while guiding the host through target, scope, mode, and roster choices before dispatch.

Architecture: Add a pure qualification contract that evaluates the frozen worker roster without changing provider authority. Route the selected policy through parser/profile resolution, roster construction, run metadata, resume validation, progress, report, and status. Update the host skill to ask only missing first-dispatch questions and to offer a current-host advisory perspective separately from fresh provider workers.

Tech Stack: Python 3.11+ standard library, argparse, dataclasses, pytest, Markdown, PlantUML, generated Codex/Claude plugin projections.

---

## Outcome (2026-09-08, executed)

Shipped in v0.8.0. The plan below is kept as the historical record; where it
disagrees with the code, the code is correct. Three things went differently:

- **The default is `cross-provider`, not `distinct-sessions`.** Revision note
  item 1 argued for the compatible default on the strength of not breaking
  existing rosters. There are no existing installations, which removed the
  only argument for the weaker default, so the design's original choice
  stands. `distinct-sessions` and `distinct-models` are explicit selections.
  The end-to-end suite names its policy at each judging dispatch instead of
  `qualify()` special-casing the `fake` transport.
- **`fresh_host_worker` is not added to `trust.ROSTER_KEYS`.** Revision note
  item 3 had that backwards. The field is stripped before
  `validate_roster_entry` in `_validated_roster_entries` instead, which keeps
  a derived runtime field out of the user-authorable roster-file surface.
- **Task 0 was unnecessary.** The near-cap files were never grown, so no
  split was needed; `max-loc` passes with `report.py` the tightest at 758.

Work not in the original task list, found while executing: `--fresh-host-worker`
was entirely non-functional, because the advisory-host filter deleted the spec
that had just been marked fresh. It shipped with no tests, which is why it
survived review.

## Revision note (2026-09-08)

This plan was revised after three independent pre-implementation reviews (a
direct `/code-review` pass, plus `afriend` runs `run-20260908T134814-d56ebfa4`
and `run-20260908T141001-c386d672`). Every code claim below was verified
against the tree at `2f4710d`. Four decisions changed as a result:

1. **The default policy is `distinct-sessions`, not `cross-provider`.** The
   design doc says "existing behavior is the default: `cross-provider`
   requires two non-host provider families" (design §Configuration and
   compatibility), but that is factually wrong about the current code:
   `roster_for_run` (`friends.py:391`) admits *any* two `independent` specs
   regardless of provider family. Defaulting to `cross-provider` would newly
   refuse every same-provider judging roster, breaking `test_run_end_to_end_loop.py`,
   `_basics`, `_gate`, `_orchestrator*`, `_roster`, and `test_ceiling_reach.py`
   — all of which dispatch two `fake:` friends. `distinct-sessions` *is*
   today's behavior, so it is the compatible default and `cross-provider`
   becomes an opt-in strengthening. Task 7 corrects the design doc sentence.
2. **`distinct-sessions` must be reported honestly.** Its predicate (distinct
   roster names) is already an unconditional invariant enforced earlier by
   `validate_roster_uniqueness` (`adapters.py:579`), so it verifies nothing
   additional. That is acceptable *as the default* only if the report states
   what the policy did not check. Task 5 requires that wording and tests it.
3. **Scaffolding is now explicit work, not an assumption.** `ROSTER_KEYS`
   (`trust.py:20`), `validate_safe_setting`'s choices branches
   (`reviewprofiles.py:104`), `_validate_saved_setting`'s type sets
   (`runmeta.py:200`), the host-family pre-filter (`friends.py:196-198`), and
   the resume `independent` coercion (`runmeta.py:346-357`) each now have a
   named step in the task that depends on them.
4. **LOC headroom is created before it is consumed.** `tests/test_docs.py`
   (771) and `tests/test_run_end_to_end_orchestrator.py` (771) sit 6 lines
   under the 777 cap enforced by `scripts/check_max_loc.py`. Task 0 splits
   them first, as behavior-free refactors.

---

## File structure

- src/afriend/qualification.py: Pure policy constants and qualification projection for a resolved roster.
- src/afriend/adapters.py: Persist explicit fresh-host-worker intent with FriendSpec; host-role marking.
- src/afriend/trust.py: Admit the new roster key so frozen rosters stay resumable.
- src/afriend/cliargs.py, reviewprofiles.py, commands/profiles.py: Parse and persist declarative policy selection.
- src/afriend/commands/friends.py: Preserve explicit fresh host workers and admit judging runs before creating a run directory.
- src/afriend/commands/runmeta*.py: Freeze and restore policy and roster evidence.
- src/afriend/progress.py, report.py, commands/status.py: Render safe, non-overclaimed qualification facts.
- src/afriend/events.py, orchestrator.py: Report worker completion without describing finished work as queued.
- src/afriend/assets/entrypoints, README.md, docs/architecture/skill-routing.puml: First-dispatch interaction and current documentation.

### Task 0: Create LOC headroom before anything consumes it

Files:
- Modify: tests/test_docs.py (771 lines; 6 under the 777 cap)
- Modify: tests/test_run_end_to_end_orchestrator.py (771 lines; 6 under the cap)
- Modify: tests/test_runmeta_migration.py (762 lines; 15 under the cap)
- Create: tests/test_docs_dispatch_setup.py, tests/test_run_end_to_end_orchestrator_schema.py

This task changes no behavior and adds no assertions. It only moves existing
test functions into new files so later tasks have room. `make quality` runs
`max-loc`, which fires at Task 8 otherwise — five commits after the cause.

- [ ] Step 1: Record the starting state.

    python3 scripts/check_max_loc.py
    wc -l tests/test_docs.py tests/test_run_end_to_end_orchestrator.py tests/test_runmeta_migration.py

  Expected: PASS, and the three counts above.

- [ ] Step 2: Move whole test functions (never partial ones) out of each file
  until each sits at or below 700 lines, leaving ~77 lines of headroom.
  Preserve imports and fixtures in both halves; do not rename or edit any
  moved assertion.

- [ ] Step 3: Run uv run pytest tests/test_docs.py tests/test_docs_dispatch_setup.py tests/test_run_end_to_end_orchestrator.py tests/test_run_end_to_end_orchestrator_schema.py tests/test_runmeta_migration.py -q.
  Expected: PASS with the same total test count as before the split.

- [ ] Step 4: Run python3 scripts/check_max_loc.py.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add tests/
    git commit -m "test: split near-cap test files for qualification work"

### Task 1: Define a pure qualification contract

Files:
- Create: src/afriend/qualification.py
- Modify: src/afriend/adapters.py
- Modify: src/afriend/trust.py
- Create: tests/test_qualification.py
- Modify: tests/test_model_selection.py, tests/test_trust.py

- [ ] Step 1: Write failing policy tests.

    def test_distinct_sessions_is_the_default_and_admits_same_provider():
        specs = [worker("codex-a", "codex", "gpt-a"), worker("codex-b", "codex", "gpt-a")]
        assert qualify(specs, DEFAULT_QUALIFICATION_POLICY).qualified
        assert DEFAULT_QUALIFICATION_POLICY == "distinct-sessions"

    def test_cross_provider_requires_two_worker_provider_families():
        result = qualify([worker("codex-a", "codex", "gpt-a"),
                          worker("claude-a", "claude", "sonnet")], "cross-provider")
        assert result.qualified is True
        assert result.qualifying_names == ("codex-a", "claude-a")
        assert not qualify([worker("codex-a", "codex", "gpt-a"),
                            worker("codex-b", "codex", "gpt-b")], "cross-provider").qualified

    def test_distinct_models_requires_different_concrete_requested_models():
        assert qualify([worker("a", "codex", "gpt-a"),
                        worker("b", "codex", "gpt-b")], "distinct-models").qualified
        assert not qualify([worker("a", "codex", "gpt-a"),
                            worker("b", "codex", None, "cli-default")],
                            "distinct-models").qualified

    def test_distinct_models_rejects_label_strings_as_identities():
        # design: "Labels such as fast, thorough, default, or unknown are not
        # model identities". MODEL_RE admits them, so qualify() must not.
        for label in ("fast", "thorough", "default", "unknown"):
            specs = [worker("a", "codex", label), worker("b", "codex", "gpt-b")]
            result = qualify(specs, "distinct-models")
            assert not result.qualified
            assert label in (result.reason or "")

    def test_advisory_host_never_qualifies():
        advisory = replace(worker("claude-host", "claude", "sonnet"),
                           independent=False, host_self_review=True)
        assert not qualify([worker("codex-a", "codex", "gpt-a"), advisory],
                           "distinct-sessions").qualified

    def test_fresh_host_worker_is_an_accepted_roster_key():
        # trust.ROSTER_KEYS gates resume; a serialized FriendSpec field that is
        # not in it makes every new run unresumable.
        validate_roster_entry({"name": "n", "cli": "claude", "lens": "ops",
                               "fresh_host_worker": True})

Use a local worker helper returning a doc-scope FriendSpec. Add malformed
fresh_host_worker resume-row coverage to tests/test_model_selection.py.

- [ ] Step 2: Run uv run pytest tests/test_qualification.py tests/test_trust.py -q.
  Expected: FAIL because afriend.qualification does not exist and ROSTER_KEYS
  rejects `fresh_host_worker`.

- [ ] Step 3: Implement the minimal contract.

    QUALIFICATION_POLICIES = ("cross-provider", "distinct-sessions", "distinct-models")
    DEFAULT_QUALIFICATION_POLICY = "distinct-sessions"
    CONCRETE_MODEL_SOURCES = frozenset(
        {"invocation", "explicit-friend", "roster", "provider-setting", "adapter-default"}
    )
    # design §Participant properties: these are labels, not identities.
    NON_IDENTITY_MODEL_LABELS = frozenset(
        {"fast", "thorough", "default", "unknown", "auto", "inherit"}
    )

    @dataclass(frozen=True)
    class Qualification:
        policy: str
        qualified: bool
        qualifying_names: tuple[str, ...]
        provider_families: tuple[str, ...]
        reason: str | None

    def qualify(specs: Sequence[FriendSpec], policy: str) -> Qualification:
        # validate policy; project eligible workers; return Qualification

Validate policy before inspecting specs. Exclude `independent=False` and
`host_self_review=True`. Require two distinct cli families for
`cross-provider`; two distinct roster names for `distinct-sessions`; and for
`distinct-models`, two different nonempty model request strings whose source is
in CONCRETE_MODEL_SOURCES and whose casefolded value is not in
NON_IDENTITY_MODEL_LABELS. Describe results as an exact *requested* model,
never a verified backend model.

Add `fresh_host_worker: bool = False` to FriendSpec, and add
`"fresh_host_worker"` to `trust.ROSTER_KEYS`. Both are required together:
`_base_meta` serializes specs with `dataclasses.asdict` (`runmeta.py:169`), so
a field absent from ROSTER_KEYS makes every newly created run fail resume
validation in `_validated_roster_entries` (`runmeta.py:369`). Preserve `False`
for existing configuration and migration data.

- [ ] Step 4: Run uv run pytest tests/test_qualification.py tests/test_trust.py tests/test_model_selection.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/qualification.py src/afriend/adapters.py src/afriend/trust.py tests/test_qualification.py tests/test_trust.py tests/test_model_selection.py
    git commit -m "feat: define roster qualification policies"

### Task 2: Add declarative policy and fresh host-worker selection

Files:
- Modify: src/afriend/cliargs.py
- Modify: src/afriend/reviewprofiles.py
- Modify: src/afriend/commands/profiles.py
- Modify: tests/test_cliargs.py, tests/test_profiles_command.py

- [ ] Step 1: Write failing parser and profile tests.

    def test_run_parses_a_task_only_qualification_policy():
        args = build_parser().parse_args(
            ["run", "spec.md", "--qualification-policy", "distinct-models"]
        )
        assert args.qualification_policy == "distinct-models"
        assert "qualification_policy" in args._profile_settings_explicit

    def test_fresh_host_worker_parses_without_an_explicit_host_provider():
        # The host is normally env-detected (readiness.HOST_ENV_MARKERS), and
        # is unknown at build_parser() time. Refusing here would break the
        # only case the design cares about: a fresh worker inside Claude Code.
        args = build_parser().parse_args(["run", "spec.md", "--fresh-host-worker"])
        assert args.fresh_host_worker is True

    def test_profile_can_store_policy(tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        sessionconfig.create_profile(
            "two-models", "balanced", {"qualification_policy": "distinct-models"}
        )
        profile = reviewprofiles.resolve("two-models", sessionconfig.load().profiles)
        assert profile.settings["qualification_policy"] == "distinct-models"

    def test_profile_rejects_an_unknown_policy_value():
        with pytest.raises(UsageError, match="qualification_policy must be one of"):
            validate_safe_setting("qualification_policy", "distinct-sessons")

- [ ] Step 2: Run uv run pytest tests/test_cliargs.py tests/test_profiles_command.py -q.
  Expected: FAIL because neither control exists.

- [ ] Step 3: Implement declarative controls.

Add `--qualification-policy` with the three choices, default None, and
`_ExplicitProfileSettingAction`. Add `--fresh-host-worker` as a boolean with no
parser-time cross-flag validation — the host is env-detected, so that check
belongs in Task 3 where `detected_host` is known.

Add `qualification_policy` to `SAFE_FIELDS` **and** add a matching choices
branch to `validate_safe_setting` (`reviewprofiles.py:104`). Without the
branch the value falls through to the trailing
`profile {field} must be a positive integer` check, which writes the profile
successfully and then fails every later `sessionconfig.load()` — bricking the
user's configuration until they hand-edit it.

Resolve absence to `DEFAULT_QUALIFICATION_POLICY`; an explicit run flag wins
over a profile value. The option changes no provider enablement, tool
authority, sandboxing, or model selection.

- [ ] Step 4: Run uv run pytest tests/test_cliargs.py tests/test_profiles_command.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/cliargs.py src/afriend/reviewprofiles.py src/afriend/commands/profiles.py tests/test_cliargs.py tests/test_profiles_command.py
    git commit -m "feat: configure roster qualification policy"

### Task 3: Preserve fresh host workers and admit judging runs

Files:
- Modify: src/afriend/commands/friends.py
- Modify: src/afriend/adapters.py
- Modify: tests/test_roster.py, tests/test_advisory_host_participation.py

- [ ] Step 1: Write failing role and admission tests.

    def test_explicit_fresh_host_worker_survives_the_host_family_filter():
        # friends.py:196-198 deletes host-family specs BEFORE mark_host_role
        # runs, and effective_host_inclusion() is False for a Claude host. So
        # --friend claude:red --fresh-host-worker currently vanishes entirely.
        args = run_args(friend=["codex:ops", "claude:red"], fresh_host_worker=True)
        specs = resolve_friends(args, registry, None, [], authority).specs
        assert [s.name for s in specs] == ["codex-ops-0", "claude-red-1"]

    def test_explicit_fresh_host_worker_is_not_rewritten_as_host_advisory():
        specs = mark_host_role([
            worker("codex", "codex", "gpt-a"),
            replace(worker("claude", "claude", "sonnet"), fresh_host_worker=True),
        ], "claude")
        assert [(s.independent, s.host_self_review) for s in specs] == [
            (True, False), (True, False)
        ]

    def test_discovered_host_family_spec_stays_advisory():
        specs = mark_host_role([worker("claude", "claude", "sonnet")], "claude")
        assert (specs[0].independent, specs[0].host_self_review) == (False, True)

    def test_fresh_host_worker_without_a_matching_friend_is_refused():
        with pytest.raises(UsageError, match="--fresh-host-worker needs an explicit"):
            resolve_friends(run_args(friend=["codex:ops"], fresh_host_worker=True), ...)

    def test_same_provider_roster_refuses_cross_provider_before_run_creation(tmp_path):
        result = run_with(tmp_path, "--mode", "crossexam",
                          "--qualification-policy", "cross-provider",
                          "--friend", "fake:good", "--friend", "fake:second")
        assert result.returncode == 3
        assert not list((tmp_path / "runs").glob("run-*"))

    def test_default_policy_still_admits_two_same_provider_workers(tmp_path):
        # Regression guard for the compatibility decision in the revision note.
        result = run_with(tmp_path, "--mode", "crossexam",
                          "--friend", "fake:good", "--friend", "fake:second")
        assert result.returncode in {0, 1, 10, 11, 12}

- [ ] Step 2: Run uv run pytest tests/test_roster.py tests/test_advisory_host_participation.py -q.
  Expected: FAIL because the filter drops the spec and no policy is evaluated.

- [ ] Step 3: Implement role preservation and pre-run admission.

In `friends.py:196-198`, exempt specs carrying explicit fresh-host-worker
intent from the `spec.cli != host` deletion. Set `fresh_host_worker=True` only
on explicit `--friend` specs whose cli equals the detected host, and only when
`--fresh-host-worker` was passed; refuse with a clear `UsageError` when the
flag is given but no such spec exists. Automatic discovery, roster files, and
`--include-self` remain advisory when they select the hosting provider.

Update `mark_host_role` so a spec with `fresh_host_worker=True` keeps
`independent=True, host_self_review=False`; every other host-family spec is
marked advisory exactly as today.

Store `Qualification` on `ResolvedRoster`. After the existing roster-uniqueness
and authority checks in `roster_for_run`, call `qualify(specs, effective_policy)`.
For non-`report` modes, raise `NoFriendsError` before `RunStore` creation when
it is false. The error names policy, worker names, provider families, and
reason; it never calls same-provider workers cross-provider independent.

- [ ] Step 4: Run uv run pytest tests/test_roster.py tests/test_advisory_host_participation.py tests/test_run_end_to_end_crossexam.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/commands/friends.py src/afriend/adapters.py tests/test_roster.py tests/test_advisory_host_participation.py
    git commit -m "feat: admit judging rosters under a qualification policy"

### Task 4: Freeze and restore evidence policy

Files:
- Modify: src/afriend/commands/runmeta.py
- Modify: src/afriend/commands/runmeta_migration.py
- Modify: src/afriend/commands/runmeta_restore.py
- Modify: src/afriend/commands/friends.py (resume branch)
- Modify: tests/test_resume_findings.py, tests/test_judging_recovery.py, tests/test_runmeta_migration.py, tests/test_run_end_to_end_orchestrator_schema.py

- [ ] Step 1: Write failing freeze and resume tests.

    def test_resume_uses_frozen_policy_after_profile_change(tmp_path):
        halted = halted_run(tmp_path, policy="distinct-sessions")
        change_default_profile("cross-provider")
        assert resume(tmp_path, halted.name).returncode in {0, 1, 10, 11, 12}
        assert run_json(tmp_path)["qualification"]["policy"] == "distinct-sessions"

    def test_resume_restores_the_frozen_qualification_without_reprojecting(tmp_path):
        # friends.py:370-376 builds ResolvedRoster directly on resume and never
        # calls resolve_friends, so the frozen payload is the only source.
        halted = halted_run(tmp_path, policy="distinct-models")
        meta = run_json(tmp_path)
        assert resume(tmp_path, halted.name).returncode in {0, 1, 10, 11, 12}
        assert run_json(tmp_path)["qualification"] == meta["qualification"]

    def test_resume_accepts_a_saved_fresh_host_worker(tmp_path):
        # runmeta.py:346-357 coerces independent = (cli != detected_host) and
        # raises on mismatch; a saved fresh host worker must be exempt.
        halted = halted_run(tmp_path, host="claude",
                            roster=[{"cli": "claude", "fresh_host_worker": True,
                                     "independent": True, "host_self_review": False}])
        assert resume(tmp_path, halted.name).returncode in {0, 1, 10, 11, 12}

    def test_resume_rejects_an_unknown_saved_policy(tmp_path):
        write_meta(tmp_path, qualification_policy="distinct-sessons")
        assert resume(tmp_path, name).returncode == 2

    def test_migration_projects_legacy_runs_to_the_compatible_policy():
        migrated = migrate_meta({"schema_version": 3, "roster": [...]})
        assert migrated["schema_version"] == 4
        assert migrated["qualification"]["policy"] == "distinct-sessions"

- [ ] Step 2: Run uv run pytest tests/test_resume_findings.py tests/test_judging_recovery.py tests/test_runmeta_migration.py -q.
  Expected: FAIL because no qualification payload is frozen and schema is 3.

- [ ] Step 3: Implement immutable metadata and resume validation.

Add `qualification_policy` to `_RESUMABLE_ARGS` **and** to `_STRING_SETTINGS`,
**and** add a `choices = QUALIFICATION_POLICIES` branch to
`_validate_saved_setting` (`runmeta.py:200`). That function is an if-chain with
no else: a name in `_RESUMABLE_ARGS` but in none of the type sets passes
through unvalidated, and `restore_args` (`runmeta_restore.py:162`) then
`setattr`s it straight from run.json — the file whose module docstring says
resume treats it as hostile input (`resumevalidation.py:1-5`).

Write:

    "qualification": {
        "policy": qualification.policy,
        "qualified": qualification.qualified,
        "qualifying_names": list(qualification.qualifying_names),
        "provider_families": list(qualification.provider_families),
        "reason": qualification.reason,
    },

In `_validated_roster_entries` (`runmeta.py:369`), add `fresh_host_worker` to
the keys stripped before `validate_roster_entry`, and exempt a row with
`fresh_host_worker=True` from the `expected_independent` coercion at
`runmeta.py:346-357` — that block currently forces
`independent = (cli != detected_host)` and raises on disagreement, which would
reject every saved fresh host worker.

In the resume branch of `roster_for_run` (`friends.py:370-376`), populate
`ResolvedRoster.qualification` from the frozen payload rather than calling
`qualify()` again. `run_meta()` (`run.py:244`) rewrites run.json on resume too,
so a missing value would either raise or overwrite the frozen record with null.
Validate only that the saved policy is a known value and that the payload shape
is well-formed — **not** structural equality against a fresh projection, which
would permanently break resume for every run frozen by an earlier version whose
`qualify()` projected different fields.

Increase metadata schema to 4 and migrate schemas 1-3 by projecting
`distinct-sessions` from their stored roster, matching the pre-change
guarantee. Update the two existing assertions that hard-code 3
(`tests/test_runmeta_migration.py`, `tests/test_run_end_to_end_orchestrator_schema.py`).

- [ ] Step 4: Run uv run pytest tests/test_resume_findings.py tests/test_judging_recovery.py tests/test_runmeta_migration.py tests/test_run_end_to_end_orchestrator_schema.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/commands/ tests/test_resume_findings.py tests/test_judging_recovery.py tests/test_runmeta_migration.py tests/test_run_end_to_end_orchestrator_schema.py
    git commit -m "feat: freeze roster qualification evidence"

### Task 5: Render safe qualification facts

Files:
- Modify: src/afriend/progress.py
- Modify: src/afriend/report.py (719 lines; keep the new section under ~50)
- Modify: src/afriend/commands/status.py
- Modify: tests/test_progress.py, tests/test_report.py, tests/test_report_model_selection.py
- Modify: tests/test_status.py (739 lines — this file EXISTS; move overflow into tests/test_status_rendering.py, 129 lines)

- [ ] Step 1: Write failing disclosure tests.

    def test_progress_names_policy_and_requested_models(capsys):
        Progress().resolved_roster(specs, qualification=qualification)
        assert "policy: distinct-models" in capsys.readouterr().err

    def test_report_labels_same_provider_policy_without_overclaiming():
        text = render(meta(policy="distinct-models", families=["codex"]))
        assert "qualified under distinct-models" in text
        assert "not cross-provider" in text
        assert "backend model verified" not in text

    def test_report_states_what_the_default_policy_did_not_verify():
        # distinct-sessions adds nothing beyond validate_roster_uniqueness, so
        # the report must not let it read as independence evidence.
        text = render(meta(policy="distinct-sessions", families=["codex"]))
        assert "distinct worker sessions only" in text
        assert "provider family and model were not compared" in text

    def test_status_exposes_safe_qualification_projection(tmp_path):
        summary = summarize(write_run(tmp_path, qualification=payload()), root=tmp_path)
        assert summary["qualification"]["policy"] == "distinct-sessions"

    def test_status_tolerates_a_run_without_qualification(tmp_path):
        # summarize() reads run.json raw (no migrate_meta) and guards every
        # field; a pre-existing run has no qualification key at all.
        summary = summarize(write_run(tmp_path, qualification=None), root=tmp_path)
        assert summary["qualification"] is None

    def test_status_tolerates_a_malformed_qualification(tmp_path):
        summary = summarize(write_run(tmp_path, qualification="nonsense"), root=tmp_path)
        assert summary["qualification"] is None

- [ ] Step 2: Run uv run pytest tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py tests/test_status.py -q.
  Expected: FAIL because renderers omit qualification facts.

- [ ] Step 3: Implement fact-only disclosure.

Extend progress with one policy summary after the roster. Keep existing
provenance language and call exact model strings *requested* models. Add a
Qualification report section before Friends. An alternative-policy success must
say "qualified under X; not cross-provider". A `distinct-sessions` result must
additionally state that only session distinctness was checked and that provider
family and model were not compared. Label a fresh host-provider worker
separately from host-self-review advisory, and disclose its shared host family.

Raise the status schema version and project only policy, boolean result, names,
provider families, and reason. Follow the existing defensive style in
`summarize` (`status.py:504`), which reads run.json raw without `migrate_meta`
and `isinstance`-guards every field: a missing or non-dict `qualification` must
project to `None`, never raise. Do not read prompts, raw responses, stderr, or
provider transcript text.

- [ ] Step 4: Run uv run pytest tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py tests/test_status.py tests/test_status_rendering.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/progress.py src/afriend/report.py src/afriend/commands/status.py tests/
    git commit -m "feat: report roster qualification evidence"

### Task 6: Report worker completion as completion

Files:
- Modify: src/afriend/events.py, src/afriend/orchestrator.py
- Modify: tests/test_events.py (or the nearest existing lifecycle test module)

The design names two problems this work exists to fix; this is the second one
("The host receives a completion event for each worker that includes its final
state and the next action. It must not describe a completed worker as queued
work."). No task in the previous revision touched it.

- [ ] Step 1: Write a failing lifecycle test.

    def test_completed_worker_is_not_reported_as_queued():
        events = drain(run_two_friends(first="ok", second="slow"))
        finished = [e for e in events if e.friend == "first"]
        assert finished[-1].state == "completed"
        assert all(e.state != "queued" for e in finished[1:])

    def test_completion_event_carries_final_state_and_next_action():
        event = last_event_for("first")
        assert event.next_action in NEXT_ACTIONS
        assert event.final_state in {"ok", "failed", "timeout", "refused"}

- [ ] Step 2: Run uv run pytest tests/test_events.py -q.
  Expected: FAIL.

- [ ] Step 3: Emit a terminal per-worker completion event carrying final state
  and next action, and stop re-rendering a finished worker in any queued or
  pending position. Change no claim, ledger, or judging semantics.

- [ ] Step 4: Run uv run pytest tests/test_events.py tests/test_progress.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/events.py src/afriend/orchestrator.py tests/test_events.py
    git commit -m "fix: report worker completion as completion"

### Task 7: Update guidance, docs, diagrams, design correction, and plugin projection

Files:
- Modify: src/afriend/assets/entrypoints/afriend/SKILL.md
- Modify: src/afriend/assets/entrypoints/review/SKILL.md
- Modify: src/afriend/assets/entrypoints/configure/SKILL.md
- Modify: src/afriend/assets/entrypoints/afriend/references/modes.md
- Modify: docs/superpowers/specs/2026-09-08-qualifying-roster-and-dispatch-setup-design.md
- Modify: README.md, docs/README.md, docs/architecture/skill-routing.puml
- Regenerate: docs/architecture/skill-routing.svg, .png, diagram-digests.json, plugins/afriend/skills
- Modify: tests/test_docs.py, tests/test_docs_dispatch_setup.py, tests/test_plugin_sync.py

- [ ] Step 1: Write failing documentation assertions.

    def test_router_requires_first_dispatch_setup_questions():
        text = canonical_router.read_text(encoding="utf-8")
        assert "Review target" in text
        assert "Evidence scope" in text
        assert "Judgment goal" in text
        assert "fresh Claude worker" in text
        assert "current Claude harness as an advisory reviewer" in text

    def test_docs_describe_exact_model_requests_without_backend_claims():
        text = README.read_text(encoding="utf-8")
        assert "exact requested model" in text
        assert "not proof of the backend model" in text

    def test_design_states_the_compatible_default():
        text = design_doc.read_text(encoding="utf-8")
        assert "`distinct-sessions` is the default" in text
        assert "Existing behavior is the default: `cross-provider`" not in text

- [ ] Step 2: Run uv run pytest tests/test_docs.py tests/test_docs_dispatch_setup.py tests/test_plugin_sync.py -q.
  Expected: FAIL because the new interaction is undocumented.

- [ ] Step 3: Write current host-facing instructions and correct the design.

Correct the design doc's compatibility claim: `distinct-sessions` is the
default because it is what the current admission check already guarantees;
`cross-provider` is an opt-in strengthening. Keep every other design statement.

On first activation ask only missing answers, in order: Review target, Evidence
scope, then Judgment goal. Reuse task setup for ordinary follow-ups and
preflight again only for a requested new loop iteration or ambiguity.

When plan/review and plural changes are available, propose the complete named
composite and enumerate every source, summarizing rather than listing once the
change set exceeds a readable size, and allow change/cancel before dispatch. If
the roster is insufficient, state actual workers, requested models, provider
families, policy, and feasible choices: another same-provider worker under an
alternative policy; a fresh host-provider worker; current harness advisory;
configure another provider; or report downgrade.

Explain that the current harness cannot qualify. A fresh worker from the host
provider is a separate execution, may qualify alongside a different provider,
and has disclosed host-family correlation. Keep model requests, provider
enablement, external-tool authority, and sandboxing separate.

Document explicitly that the `distinct-models` confirmation requirement is host
guidance, not a CLI control: `afriend run --qualification-policy distinct-models`
does not itself prompt, so an unattended caller can dispatch without
confirmation. State this as a known limitation rather than implying enforcement.

Update skill-routing.puml with first-dispatch setup -> selected target/scope/
policy -> confirmation -> compose/run and the insufficient-roster branch.
Regenerate the image/digest by the repository diagram command. Run make
plugin-sync-copy; never edit the generated projection under plugins/ manually.

- [ ] Step 4: Run make plugin-sync-copy && make plugin-sync && uv run pytest tests/test_docs.py tests/test_docs_dispatch_setup.py tests/test_plugin_sync.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/assets README.md docs plugins/afriend/skills tests/
    git commit -m "docs: explain qualifying roster setup"

### Task 8: Integrated verification

Files:
- Modify: only a file directly implicated by a failing verification assertion.

- [ ] Step 1: Run the behavioral matrix.

    uv run pytest tests/test_qualification.py tests/test_trust.py tests/test_cliargs.py \
      tests/test_profiles_command.py tests/test_roster.py tests/test_model_selection.py \
      tests/test_advisory_host_participation.py tests/test_run_end_to_end_crossexam.py \
      tests/test_resume_findings.py tests/test_judging_recovery.py \
      tests/test_runmeta_migration.py tests/test_run_end_to_end_orchestrator.py \
      tests/test_run_end_to_end_orchestrator_schema.py tests/test_events.py \
      tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py \
      tests/test_status.py tests/test_status_rendering.py tests/test_docs.py \
      tests/test_docs_dispatch_setup.py tests/test_plugin_sync.py -q

Expected: PASS.

- [ ] Step 2: Confirm the compatibility guarantee explicitly.

    uv run pytest tests/test_run_end_to_end_loop.py tests/test_run_end_to_end_basics.py \
      tests/test_run_end_to_end_gate.py tests/test_run_end_to_end_roster.py \
      tests/test_ceiling_reach.py -q

Expected: PASS with no new refusals. These dispatch two same-provider `fake:`
friends and are the regression surface for the default-policy decision.

- [ ] Step 3: Verify profile contract in isolated configuration.

    AF_QUALIFY_CFG=$(mktemp -d)
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles create two-models --base balanced --qualification-policy distinct-models
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles show two-models --json
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend run --help | grep qualification
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles delete two-models

Expected: JSON contains `qualification_policy: distinct-models`, the profile
survives a reload rather than failing validation, and user configuration is
untouched.

- [ ] Step 4: Run make quality.
  Expected: lint, strict type, LOC, plugin sync, version sync, wheel checks,
  and all tests PASS.

- [ ] Step 5: Check for stale claims and projection drift.

    git diff --check
    rg -n "backend model verified|same-provider independent|legacy" README.md docs src/afriend/assets plugins/afriend/skills
    git status --short

Expected: no whitespace error, no new stale wording, generated skill projection
agrees with canonical assets, and only intended files changed.

- [ ] Step 6: If verification required a repair, stage the repaired source and
  its focused test, then commit with message: fix: align roster qualification
  contracts. Do not create another commit when all verification gates pass.
