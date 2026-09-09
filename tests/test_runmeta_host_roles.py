"""Host-role restoration and the judging refusal that protects it.

The current schema always serializes ``independent`` and ``host_self_review``
for every roster entry, so an entry that omits them is malformed input rather
than an older run. Judging modes refuse it; report resumes stay readable with
the possible host marked non-independent.

There used to be a third answer: reconstruct the roles, then replay the ledger
to rebuild whatever authority state had been derived under the wrong ones.
That reconstruction is gone. Refusing is the whole behaviour now, which is why
this file tests the refusal and its two boundaries -- report mode on one side,
a frozen host on the other -- rather than a repair.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from afriend.errors import UsageError
from afriend.reviewstate import ReviewState

FIXTURES = Path(__file__).with_name("fixtures")

HOST_ROLE_REFUSAL = r"omits its host-role fields.*rerun"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _resume_args(run_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        resume=str(run_dir),
        out=None,
        artifact=None,
        friend=[],
        allow_external_tools=[],
        allow_unsandboxed_friend=False,
        unsafe_extra_args=None,
        i_accept_unsandboxed=False,
        pass_env=[],
    )


def _run_dir(tmp_path: Path, meta: dict[str, object]) -> Path:
    run_dir = tmp_path / "run-host-roles"
    run_dir.mkdir()
    round_dir = run_dir / "round-1"
    round_dir.mkdir()
    (round_dir / "REQUEST.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_dir.name,
                "round": 1,
                "question": "merge",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    return run_dir


def _resume_meta() -> dict[str, object]:
    meta = load_fixture("run_meta_current_halted.json")
    meta["invocation"].update(
        {
            "allow_unsandboxed_friend": False,
            "i_accept_unsandboxed": False,
            "unsafe_extra_args": None,
            "pass_env": [],
        }
    )
    return meta


def _detach_from_repository(meta: dict[str, object]) -> None:
    """Record a run with no repository, in every place the snapshot lives.

    The nested snapshot is authoritative and the flat fields mirror it, so
    clearing only the flat pair leaves the two disagreeing and resume refuses
    the run before it reaches the host-role logic under test.
    """
    meta["repo_root"] = None
    meta["snapshot_sha"] = None
    snapshots = [meta["snapshot"], *meta.get("snapshot_history", [])]
    for snapshot in snapshots:
        snapshot.update(
            {
                "repo_root": None,
                "commit": None,
                "tree": None,
                "source_path": None,
                "artifact_bound_to_snapshot": False,
            }
        )


def _host_resume_meta(mode: str, *, frozen_host: bool, roles: bool = False) -> dict[str, object]:
    """A two-friend run whose first entry is the orchestrating provider.

    ``roles`` writes the role fields the current schema always emits. Leaving
    it False is the malformed shape the refusal exists for, so most tests here
    pick one or the other deliberately.
    """
    meta = _resume_meta()
    _detach_from_repository(meta)
    meta["invocation"].update(
        {
            "mode": mode,
            "include_self": None,
            "host_provider": None,
        }
    )
    meta["mode"] = mode
    meta["roster"] = [
        {
            "name": "codex-ops",
            "cli": "codex",
            "lens": "ops",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 900,
        },
        {
            "name": "fake-security",
            "cli": "fake",
            "lens": "security",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 900,
        },
    ]
    if roles:
        meta["roster"][0].update({"independent": False, "host_self_review": True})
        meta["roster"][1].update({"independent": True, "host_self_review": False})
    meta["friends"] = [
        {
            "name": "codex-ops",
            "model": None,
            "effort": None,
            "round": 1,
            "status": "ok",
        },
        {
            "name": "fake-security",
            "model": None,
            "effort": None,
            "round": 1,
            "status": "ok",
        },
    ]
    if frozen_host:
        meta["detected_host"] = "codex"
        meta["effective_include_self"] = True
    return meta


def test_host_roles_are_restored_from_frozen_host_and_audit_rows_follow(tmp_path):
    from afriend.commands.runmeta import _restore_args
    from afriend.report import render

    run_dir = _run_dir(tmp_path, _host_resume_meta("report", frozen_host=True))

    restored = _restore_args(_resume_args(run_dir))

    host = restored._resume_roster[0]
    assert host.host_self_review is True
    assert host.independent is False
    assert restored._resume_roster[1].independent is True
    assert restored._resume_meta["roster"][0]["host_self_review"] is True
    assert restored._resume_meta["roster"][0]["independent"] is False
    host_row = restored._resume_meta["friends"][0]
    assert host_row["host_self_review"] is True
    assert host_row["independent"] is False
    report = render(ReviewState(), restored._resume_meta)
    rendered_host = next(line for line in report.splitlines() if line.startswith("| codex-ops |"))
    assert "host-self-review (advisory)" in rendered_host
    assert "False" in rendered_host


def test_resume_leaves_profile_absent_without_reading_session_default(tmp_path, monkeypatch):
    from afriend.cliargs import build_parser
    from afriend.commands import runmeta

    run_dir = _run_dir(tmp_path, _host_resume_meta("report", frozen_host=True))

    direct = runmeta._restore_args(_resume_args(run_dir))
    assert direct.profile is None

    def session_default_must_not_be_read():
        raise AssertionError("a resume must not read the current session profile default")

    monkeypatch.setattr(runmeta, "load_session_config", session_default_must_not_be_read)
    parsed = build_parser().parse_args(["run", "--resume", str(run_dir)])
    restored, _ = runmeta.validate_run_args(parsed)

    assert restored.profile is None
    assert restored.mode == "report"


@pytest.mark.parametrize("mode", ["crossexam", "gate", "loop"])
def test_frozen_host_cannot_satisfy_judging_admission(monkeypatch, tmp_path, mode):
    """Roles recorded correctly, and the host still is not a second judge.

    The roster is well formed here on purpose: this is the admission rule, not
    the refusal below, and the two must not be able to stand in for each other.
    """
    from afriend.commands import friends as friends_module
    from afriend.commands.runmeta import _restore_args
    from afriend.errors import NoFriendsError

    run_dir = _run_dir(tmp_path, _host_resume_meta(mode, frozen_host=True, roles=True))
    restored = _restore_args(_resume_args(run_dir))
    monkeypatch.setattr(friends_module, "validate_resume_capabilities", lambda *args: None)

    with pytest.raises(NoFriendsError, match="two independent friends"):
        friends_module.roster_for_run(restored, {}, None, [])


@pytest.mark.parametrize("mode", ["crossexam", "gate", "loop"])
@pytest.mark.parametrize("host_cli", ["codex", "agy"])
def test_ambiguous_host_role_fails_closed_for_judging_resume(tmp_path, mode, host_cli):
    from afriend.commands.runmeta import _restore_args

    meta = _host_resume_meta(mode, frozen_host=False)
    meta["roster"][0]["cli"] = host_cli
    run_dir = _run_dir(tmp_path, meta)

    with pytest.raises(UsageError, match=HOST_ROLE_REFUSAL):
        _restore_args(_resume_args(run_dir))


@pytest.mark.parametrize("mode", ["crossexam", "gate", "loop"])
def test_judging_resume_refuses_omitted_host_roles_even_with_a_frozen_host(tmp_path, mode):
    """A frozen host makes the roles derivable, which is not the same as sound.

    The roles can be reconstructed from ``detected_host``, but the authority
    state saved next to those rows was derived by whatever wrote them, under a
    host-role model this version cannot confirm. Deriving the roles and
    carrying that state forward is how an advisory host reaches a verdict, so
    a frozen host does not buy an exemption from the refusal.
    """
    from afriend.commands.runmeta import _restore_args

    meta = _host_resume_meta(mode, frozen_host=True)
    meta.update({"claim_states": {"c-0001@1": "settled-refuted"}, "incomplete": False})
    run_dir = _run_dir(tmp_path, meta)

    with pytest.raises(UsageError, match=HOST_ROLE_REFUSAL):
        _restore_args(_resume_args(run_dir))


def test_saved_friend_audit_role_must_match_frozen_roster(tmp_path):
    from afriend.commands.runmeta import _restore_args

    meta = _host_resume_meta("report", frozen_host=True)
    meta["friends"][0].update({"independent": True, "host_self_review": False})
    run_dir = _run_dir(tmp_path, meta)

    with pytest.raises(UsageError, match=r"friends\[0\].*frozen roster"):
        _restore_args(_resume_args(run_dir))


def test_resumed_participation_floor_excludes_successful_host(tmp_path):
    from afriend.commands.runmeta import _restore_args

    meta = _host_resume_meta("report", frozen_host=True)
    meta["invocation"]["require_friends"] = 1
    meta["friends"][1]["status"] = "failed: exit 1"
    meta["successful_friend_ids"] = ["codex-ops"]
    meta["succeeded_friends"] = 1
    meta["required_friends"] = 1
    run_dir = _run_dir(tmp_path, meta)

    restored = _restore_args(_resume_args(run_dir))

    assert restored._resume_successful_friend_ids == []
    assert restored._resume_meta["succeeded_friends"] == 0


def test_ambiguous_report_labels_possible_host_role_unknown(tmp_path):
    from afriend.commands.runmeta import _restore_args
    from afriend.report import render

    run_dir = _run_dir(tmp_path, _host_resume_meta("report", frozen_host=False))

    restored = _restore_args(_resume_args(run_dir))

    host = restored._resume_roster[0]
    assert host.independent is False
    assert host.host_self_review is False
    host_row = restored._resume_meta["friends"][0]
    assert host_row["independent"] is False
    assert host_row["host_self_review"] is False
    report = render(ReviewState(), restored._resume_meta)
    rendered_host = next(line for line in report.splitlines() if line.startswith("| codex-ops |"))
    assert "role unknown (advisory)" in rendered_host
    assert "independent reviewer" not in rendered_host
