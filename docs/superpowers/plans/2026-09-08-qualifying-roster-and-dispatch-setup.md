# Qualifying Roster and Dispatch Setup Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Let afriend explicitly qualify same-provider worker rosters under a selected evidence policy while guiding the host through target, scope, mode, and roster choices before dispatch.

Architecture: Add a pure qualification contract that evaluates the frozen worker roster without changing provider authority. Route the selected policy through parser/profile resolution, roster construction, run metadata, resume validation, progress, report, and status. Update the host skill to ask only missing first-dispatch questions and to offer a current-host advisory perspective separately from fresh provider workers.

Tech Stack: Python 3.11+ standard library, argparse, dataclasses, pytest, Markdown, PlantUML, generated Codex/Claude plugin projections.

---

## File structure

- src/afriend/qualification.py: Pure policy constants and qualification projection for a resolved roster.
- src/afriend/adapters.py: Persist explicit fresh-host-worker intent with FriendSpec.
- src/afriend/cliargs.py, reviewprofiles.py, commands/profiles.py: Parse and persist declarative policy selection.
- src/afriend/commands/friends.py, roster.py: Construct host roles and admit judging runs before creating a run directory.
- src/afriend/commands/runmeta*.py: Freeze and restore policy and roster evidence.
- src/afriend/progress.py, report.py, commands/status.py: Render safe, non-overclaimed qualification facts.
- src/afriend/assets/entrypoints, README.md, docs/architecture/skill-routing.puml: First-dispatch interaction and current documentation.

### Task 1: Define a pure qualification contract

Files:
- Create: src/afriend/qualification.py
- Modify: src/afriend/adapters.py
- Create: tests/test_qualification.py
- Modify: tests/test_model_selection.py

- [ ] Step 1: Write failing policy tests.

    def test_cross_provider_requires_two_worker_provider_families():
        result = qualify([worker("codex-a", "codex", "gpt-a"),
                          worker("claude-a", "claude", "sonnet")], "cross-provider")
        assert result.qualified is True
        assert result.qualifying_names == ("codex-a", "claude-a")

    def test_same_provider_workers_need_an_explicit_alternative_policy():
        specs = [worker("codex-a", "codex", "gpt-a"),
                 worker("codex-b", "codex", "gpt-a")]
        assert not qualify(specs, "cross-provider").qualified
        assert qualify(specs, "distinct-sessions").qualified

    def test_distinct_models_requires_different_concrete_requested_models():
        assert qualify([worker("a", "codex", "gpt-a"),
                        worker("b", "codex", "gpt-b")], "distinct-models").qualified
        assert not qualify([worker("a", "codex", "gpt-a"),
                            worker("b", "codex", None, "cli-default")],
                            "distinct-models").qualified

    def test_advisory_host_never_qualifies():
        advisory = replace(worker("claude-host", "claude", "sonnet"),
                           independent=False, host_self_review=True)
        assert not qualify([worker("codex-a", "codex", "gpt-a"), advisory],
                           "distinct-sessions").qualified

Use a local worker helper returning a doc-scope FriendSpec. Add malformed
fresh_host_worker resume-row coverage to tests/test_model_selection.py.

- [ ] Step 2: Run uv run pytest tests/test_qualification.py -q.
  Expected: FAIL because afriend.qualification does not exist.

- [ ] Step 3: Implement the minimal contract.

    QUALIFICATION_POLICIES = ("cross-provider", "distinct-sessions", "distinct-models")
    DEFAULT_QUALIFICATION_POLICY = "cross-provider"
    CONCRETE_MODEL_SOURCES = frozenset(
        {"invocation", "explicit-friend", "roster", "provider-setting", "adapter-default"}
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

Validate policy before inspecting specs. Exclude independent=False and
host_self_review=True. Require two distinct cli families for cross-provider;
two distinct roster names for distinct-sessions; and two different nonempty
model request strings with concrete sources for distinct-models. Describe this
as an exact requested model, never a verified backend model.

Add fresh_host_worker: bool = False to FriendSpec; preserve false for existing
configuration and migration data.

- [ ] Step 4: Run uv run pytest tests/test_qualification.py tests/test_model_selection.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/qualification.py src/afriend/adapters.py tests/test_qualification.py tests/test_model_selection.py
    git commit -m "feat: define roster qualification policies"

### Task 2: Add declarative policy and fresh host-worker selection

Files:
- Modify: src/afriend/cliargs.py
- Modify: src/afriend/reviewprofiles.py
- Modify: src/afriend/commands/profiles.py
- Modify: src/afriend/commands/friends.py
- Modify: src/afriend/roster.py
- Modify: tests/test_cliargs.py, tests/test_profiles_command.py, tests/test_roster.py

- [ ] Step 1: Write failing parser and role tests.

    def test_run_parses_a_task_only_qualification_policy():
        args = build_parser().parse_args(
            ["run", "spec.md", "--qualification-policy", "distinct-models"]
        )
        assert args.qualification_policy == "distinct-models"
        assert "qualification_policy" in args._profile_settings_explicit

    def test_profile_can_store_policy(tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        sessionconfig.create_profile(
            "two-models", "balanced", {"qualification_policy": "distinct-models"}
        )
        profile = reviewprofiles.resolve("two-models", sessionconfig.load().profiles)
        assert profile.settings["qualification_policy"] == "distinct-models"

    def test_explicit_fresh_host_worker_is_not_rewritten_as_host_advisory():
        specs = mark_host_role([
            worker("codex", "codex", "gpt-a"),
            replace(worker("claude", "claude", "sonnet"), fresh_host_worker=True),
        ], "claude")
        assert [(s.independent, s.host_self_review) for s in specs] == [
            (True, False), (True, False)
        ]

Also assert parser refusal when fresh-host-worker has no matching host-provider
and explicit host-provider friend.

- [ ] Step 2: Run uv run pytest tests/test_cliargs.py tests/test_profiles_command.py tests/test_roster.py -q.
  Expected: FAIL because neither control exists.

- [ ] Step 3: Implement declarative controls.

Add --qualification-policy with the three choices, default None, and
_ExplicitProfileSettingAction. Add --fresh-host-worker as a boolean. Reject
fresh-host-worker unless host-provider and an explicit matching --friend exist.

Add qualification_policy to safe profile fields and profile command settings.
Resolve absence to cross-provider; an explicit run flag wins over profile.

In explicit roster construction, set fresh_host_worker=True only on matching
explicit host-provider specs. Update mark_host_role so only those remain
independent. Automatic discovery, roster files, and include-self remain
advisory when they select the hosting provider. The option changes no provider
enablement, tool authority, sandboxing, or model selection.

- [ ] Step 4: Run uv run pytest tests/test_cliargs.py tests/test_profiles_command.py tests/test_roster.py tests/test_model_selection.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/cliargs.py src/afriend/reviewprofiles.py src/afriend/commands/profiles.py src/afriend/commands/friends.py src/afriend/roster.py tests/test_cliargs.py tests/test_profiles_command.py tests/test_roster.py tests/test_model_selection.py
    git commit -m "feat: configure roster qualification policy"

### Task 3: Enforce and freeze evidence policy

Files:
- Modify: src/afriend/commands/friends.py
- Modify: src/afriend/commands/runmeta.py
- Modify: src/afriend/commands/runmeta_migration.py
- Modify: src/afriend/commands/runmeta_restore.py
- Modify: tests/test_run_end_to_end_crossexam.py, tests/test_resume_findings.py, tests/test_judging_recovery.py

- [ ] Step 1: Write failing admission and resume tests.

    def test_same_provider_roster_refuses_cross_provider_before_run_creation(tmp_path):
        result = run_with(tmp_path, "--mode", "crossexam",
                          "--friend", "fake:good", "--friend", "fake:second")
        assert result.returncode == 3
        assert not list((tmp_path / "runs").glob("run-*"))

    def test_distinct_sessions_admits_two_same_provider_workers(tmp_path):
        result = run_with(tmp_path, "--mode", "crossexam",
                          "--qualification-policy", "distinct-sessions",
                          "--friend", "fake:good", "--friend", "fake:second")
        assert result.returncode in {0, 1, 10, 11, 12}
        assert run_json(tmp_path)["qualification"]["qualified"] is True

    def test_resume_uses_frozen_policy_after_profile_change(tmp_path):
        halted = halted_run(tmp_path, policy="distinct-sessions")
        change_default_profile("cross-provider")
        assert resume(tmp_path, halted.name).returncode in {0, 1, 10, 11, 12}
        assert run_json(tmp_path)["qualification"]["policy"] == "distinct-sessions"

- [ ] Step 2: Run uv run pytest tests/test_run_end_to_end_crossexam.py tests/test_resume_findings.py tests/test_judging_recovery.py -q.
  Expected: FAIL because judging admission only counts independent specs and no qualification payload is frozen.

- [ ] Step 3: Implement pre-run admission and immutable metadata.

Store Qualification on ResolvedRoster. After final roster uniqueness and authority
checks, call qualify(specs, effective_policy). For non-report modes, raise
NoFriendsError before RunStore creation when false. The error names policy,
worker names, provider families, and reason; it never calls same-provider
workers cross-provider independent.

Add qualification_policy to _RESUMABLE_ARGS and write:

    "qualification": {
        "policy": qualification.policy,
        "qualified": qualification.qualified,
        "qualifying_names": list(qualification.qualifying_names),
        "provider_families": list(qualification.provider_families),
        "reason": qualification.reason,
    },

Increase metadata schema to 4. Migrate schemas 1-3 by rebuilding a conservative
cross-provider projection from their stored roster. Resume validates policy,
fresh_host_worker booleans, and equality of saved payload to a fresh projection.
It restores saved policy rather than current profile/default.

- [ ] Step 4: Run uv run pytest tests/test_run_end_to_end_crossexam.py tests/test_resume_findings.py tests/test_judging_recovery.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/commands/friends.py src/afriend/commands/runmeta.py src/afriend/commands/runmeta_migration.py src/afriend/commands/runmeta_restore.py tests/test_run_end_to_end_crossexam.py tests/test_resume_findings.py tests/test_judging_recovery.py
    git commit -m "feat: freeze roster qualification evidence"

### Task 4: Render safe qualification facts

Files:
- Modify: src/afriend/progress.py
- Modify: src/afriend/report.py
- Modify: src/afriend/commands/status.py
- Modify: tests/test_progress.py, tests/test_report.py, tests/test_report_model_selection.py
- Create: tests/test_status.py

- [ ] Step 1: Write failing disclosure tests.

    def test_progress_names_policy_and_requested_models(capsys):
        Progress().resolved_roster(specs, qualification=qualification)
        assert "policy: distinct-models" in capsys.readouterr().err

    def test_report_labels_same_provider_policy_without_overclaiming():
        text = render(meta(policy="distinct-models", families=["codex"]))
        assert "qualified under distinct-models" in text
        assert "not cross-provider" in text
        assert "backend model verified" not in text

    def test_status_exposes_safe_qualification_projection(tmp_path):
        summary = summarize(write_run(tmp_path, qualification=payload()), root=tmp_path)
        assert summary["qualification"]["policy"] == "distinct-sessions"

- [ ] Step 2: Run uv run pytest tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py tests/test_status.py -q.
  Expected: FAIL because renderers omit qualification facts.

- [ ] Step 3: Implement fact-only disclosure.

Extend progress with one policy summary after the roster. Keep existing provenance
language and call exact model strings requested models. Add a Qualification
report section before Friends; alternative-policy success must say qualified
under X; not cross-provider. Label fresh host-provider worker separately from
host-self-review advisory.

Raise status schema version and project only policy, boolean result, names,
provider families, and reason. Do not read prompts, raw responses, stderr, or
provider transcript text.

- [ ] Step 4: Run uv run pytest tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py tests/test_status.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/progress.py src/afriend/report.py src/afriend/commands/status.py tests/test_progress.py tests/test_report.py tests/test_report_model_selection.py tests/test_status.py
    git commit -m "feat: report roster qualification evidence"

### Task 5: Update first-dispatch guidance, docs, diagrams, and plugin projection

Files:
- Modify: src/afriend/assets/entrypoints/afriend/SKILL.md
- Modify: src/afriend/assets/entrypoints/review/SKILL.md
- Modify: src/afriend/assets/entrypoints/configure/SKILL.md
- Modify: src/afriend/assets/entrypoints/afriend/references/modes.md
- Modify: README.md, docs/README.md, docs/architecture/skill-routing.puml
- Regenerate: docs/architecture/skill-routing.svg, docs/architecture/skill-routing.png, docs/architecture/diagram-digests.json, plugins/afriend/skills
- Modify: tests/test_docs.py, tests/test_plugin_sync.py

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

- [ ] Step 2: Run uv run pytest tests/test_docs.py tests/test_plugin_sync.py -q.
  Expected: FAIL because the new interaction is undocumented.

- [ ] Step 3: Write current host-facing instructions.

On first activation ask only missing answers, in order: Review target, Evidence
scope, then Judgment goal. Reuse task setup for ordinary follow-ups and
preflight again only for requested new loop iteration or ambiguity.

When plan/review and plural changes are available, propose the complete named
composite, enumerate every source, and allow change/cancel before dispatch. If
the roster is insufficient, state actual workers, requested models, provider
families, policy, and feasible choices: another same-provider worker under an
alternative policy; a fresh host-provider worker; current harness advisory;
configure another provider; or report downgrade.

Explain current harness cannot qualify. A fresh worker from host provider is a
separate execution, may qualify alongside a different provider, and has
disclosed host-family correlation. Keep model requests, provider enablement,
external-tool authority, and sandboxing separate.

Update skill-routing.puml with first-dispatch setup -> selected target/scope/
policy -> confirmation -> compose/run and the insufficient-roster branch.
Regenerate the image/digest by the repository diagram command. Run make
plugin-sync-copy; never edit the generated projection manually.

- [ ] Step 4: Run make plugin-sync-copy && make plugin-sync && uv run pytest tests/test_docs.py tests/test_plugin_sync.py -q.
  Expected: PASS.

- [ ] Step 5: Commit.

    git add src/afriend/assets README.md docs plugins/afriend/skills tests/test_docs.py tests/test_plugin_sync.py
    git commit -m "docs: explain qualifying roster setup"

### Task 6: Integrated verification

Files:
- Modify: only a file directly implicated by a failing verification assertion.

- [ ] Step 1: Run the behavioral matrix.

    uv run pytest tests/test_qualification.py tests/test_cliargs.py tests/test_profiles_command.py \
      tests/test_roster.py tests/test_model_selection.py tests/test_advisory_host_participation.py \
      tests/test_run_end_to_end_crossexam.py tests/test_resume_findings.py \
      tests/test_judging_recovery.py tests/test_progress.py tests/test_report.py \
      tests/test_report_model_selection.py tests/test_status.py tests/test_docs.py \
      tests/test_plugin_sync.py -q

Expected: PASS.

- [ ] Step 2: Verify profile contract in isolated configuration.

    AF_QUALIFY_CFG=$(mktemp -d)
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles create two-models --base balanced --qualification-policy distinct-models
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles show two-models --json
    XDG_CONFIG_HOME="$AF_QUALIFY_CFG" uv run afriend profiles delete two-models

Expected: JSON contains qualification_policy: distinct-models; user configuration
is untouched.

- [ ] Step 3: Run make quality.
  Expected: lint, strict type, LOC, plugin sync, version sync, wheel checks,
  and all tests PASS.

- [ ] Step 4: Check for stale claims and projection drift.

    git diff --check
    rg -n "backend model verified|same-provider independent|legacy" README.md docs src/afriend/assets plugins/afriend/skills
    git status --short

Expected: no whitespace error, no new stale wording, generated skill projection
agrees with canonical assets, and only intended files changed.

- [ ] Step 5: If verification required a repair, stage the repaired source and
  its focused test, then commit with message: fix: align roster qualification
  contracts. Do not create another commit when all verification gates pass.
