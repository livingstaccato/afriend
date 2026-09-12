"""Validation coverage for run.json at the one schema this version reads."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from runmeta_helpers import _resume_args, _resume_meta, _run_dir

from afriend.adapters import FriendSpec
from afriend.authority import DENY_ALL
from afriend.cliargs import build_parser
from afriend.commands.runmeta import (
    CURRENT_SCHEMA_VERSION,
    _base_meta,
    _validated_roster_entries,
    validate_run_args,
    validated_meta,
)
from afriend.errors import UsageError
from afriend.ledger import Ledger
from afriend.snapshots import SnapshotIdentity

# Derived from the constant, not written out: the list previously named 5 as
# a rejected version because 5 was "one past current". Bumping the schema to
# 5 turned that case into an assertion that the CURRENT version is refused,
# which the parametrized test then failed -- the literal silently changed
# meaning under the constant it was written against.
_REFUSED_VERSIONS = list(
    dict.fromkeys(
        [
            True,
            False,
            str(CURRENT_SCHEMA_VERSION),
            0,
            -1,
            CURRENT_SCHEMA_VERSION - 2,
            CURRENT_SCHEMA_VERSION - 1,
            CURRENT_SCHEMA_VERSION + 1,
            None,
        ]
    )
)


@pytest.mark.parametrize("version", _REFUSED_VERSIONS)
def test_any_version_but_the_current_one_is_refused(version):
    """One schema. Older versions are refused rather than upgraded on read.

    Every migration path was a second definition of what a run is, with its
    own defaults and reconstructions, and that is where the defects lived: a
    policy filled from the wrong default, a verdict synthesized from a roster
    whose host role was not yet known. Refusing is recoverable -- the run
    directory stays readable as plain text.
    """
    with pytest.raises(UsageError, match="is not readable by this version"):
        validated_meta({"schema_version": version})


def test_the_current_version_is_accepted():
    assert validated_meta({"schema_version": CURRENT_SCHEMA_VERSION})["schema_version"] == (
        CURRENT_SCHEMA_VERSION
    )


def test_validation_always_returns_a_deep_copy():
    raw = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "invocation": {"friend": ["fake:ops"]},
        "snapshot": {"artifact_path": "artifact/spec.md"},
    }
    before = copy.deepcopy(raw)

    migrated = validated_meta(raw)
    migrated["invocation"]["friend"].append("fake:security")
    migrated["snapshot"]["artifact_path"] = "changed"

    assert raw == before


def test_saved_roster_preserves_host_role_audit_fields():
    entry = {
        "name": "codex-ops",
        "cli": "codex",
        "lens": "ops",
        "model": None,
        "effort": None,
        "scope": "doc",
        "timeout": 30,
        "independent": False,
        "host_self_review": True,
    }

    restored = FriendSpec(**_validated_roster_entries([entry])[0])

    assert restored.independent is False
    assert restored.host_self_review is True


@pytest.mark.parametrize("field", ["independent", "host_self_review"])
def test_saved_roster_rejects_non_boolean_host_role_fields(field):
    entry = {
        "name": "codex-ops",
        "cli": "codex",
        "lens": "ops",
        "model": None,
        "effort": None,
        "scope": "doc",
        "timeout": 30,
        field: "false",
    }

    with pytest.raises(UsageError, match=field):
        _validated_roster_entries([entry])


def test_saved_roster_rejects_host_role_claimed_independent():
    entry = {
        "name": "codex-ops",
        "cli": "codex",
        "lens": "ops",
        "model": None,
        "effort": None,
        "scope": "doc",
        "timeout": 30,
        "independent": True,
        "host_self_review": True,
    }

    with pytest.raises(UsageError, match=r"host_self_review.*independent"):
        _validated_roster_entries([entry])


def test_fresh_metadata_freezes_detected_host_and_effective_self_inclusion(tmp_path):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")
    snapshot = SnapshotIdentity(
        None,
        None,
        None,
        str(artifact),
        "sha256:" + "1" * 64,
    )

    meta = _base_meta(
        SimpleNamespace(mode="report", profile="quick", merge="exact", friend=[]),
        artifact,
        snapshot.artifact_hash,
        [],
        [],
        [],
        snapshot,
        [snapshot],
        DENY_ALL,
        detected_host="codex",
        effective_include_self=True,
    )

    assert meta["detected_host"] == "codex"
    assert meta["effective_include_self"] is True


def test_fresh_metadata_records_the_resolved_profile(tmp_path):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")
    snapshot = SnapshotIdentity(None, None, None, str(artifact), "sha256:" + "2" * 64)

    meta = _base_meta(
        SimpleNamespace(mode="crossexam", profile="balanced", merge="exact", friend=[]),
        artifact,
        snapshot.artifact_hash,
        [],
        [],
        [],
        snapshot,
        [snapshot],
        DENY_ALL,
    )

    assert meta["profile"] == "balanced"
    assert meta["invocation"]["profile"] == "balanced"


def test_resume_keeps_the_saved_profile_without_reading_a_new_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    saved = SimpleNamespace(
        resume="saved-run",
        artifact=str(tmp_path / "saved-spec.md"),
        mode="loop",
        profile="thorough",
        timeout=900,
        max_friends=None,
        max_calls=None,
        max_wall_clock=7200,
        max_loop_iterations=5,
        require_friends=None,
        max_rounds=3,
        model=None,
    )
    monkeypatch.setattr("afriend.commands.runmeta._restore_args", lambda _args: saved)

    restored, _ = validate_run_args(SimpleNamespace(resume="saved-run"))

    assert restored.profile == "thorough"
    assert restored.mode == "loop"


def test_resume_rejects_explicit_repo_before_restoring_saved_arguments():
    args = build_parser().parse_args(
        ["run", "harmless.md", "--resume", "saved-run", "--repo", "/worktree"]
    )

    with pytest.raises(
        UsageError,
        match="--repo cannot be used with --resume; the saved run fixes repository scope",
    ):
        validate_run_args(args)


def _host_resume_meta(mode: str, *, frozen_host: bool) -> dict[str, object]:
    meta = _resume_meta()
    meta["repo_root"] = None
    meta["snapshot_sha"] = None
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


def _append_ledger(run_dir: Path, *records: object) -> None:
    ledger = Ledger(run_dir / "claims.jsonl", root=run_dir.parent)
    for record in records:
        ledger.append(record)


def _friend_audit(name: str, round_no: int, status: str) -> dict[str, object]:
    return {
        "name": name,
        "model": None,
        "effort": None,
        "round": round_no,
        "status": status,
    }


def _write_outstanding_request(run_dir: Path, round_no: int) -> None:
    round_dir = run_dir / f"round-{round_no}"
    round_dir.mkdir()
    (round_dir / "REQUEST.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_dir.name,
                "round": round_no,
                "question": "merge",
            }
        ),
        encoding="utf-8",
    )


def _make_second_loop_halt(meta: dict[str, object]) -> None:
    meta["invocation"]["mode"] = "loop"
    meta["mode"] = "loop"
    meta.update(
        {
            "iterations_run": 2,
            "resume_iteration": 2,
            "rounds_run": 4,
        }
    )
    meta["friends"].extend(
        [
            _friend_audit("codex-ops", 4, "ok"),
            _friend_audit("fake-security", 4, "ok"),
            _friend_audit("fake-author", 4, "ok"),
        ]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lifecycle_state", []),
        ("snapshot", []),
        (
            "snapshot",
            {
                "repo_root": [],
                "commit": None,
                "tree": None,
                "artifact_path": "",
                "artifact_hash": "",
                "predecessor": None,
            },
        ),
        ("repeat_tracker", []),
        ("invocation", []),
        ("roster", ["not-an-object"]),
    ],
)
def test_hostile_resume_shapes_are_rejected_before_namespace_construction(
    monkeypatch, tmp_path, field, value
):
    from afriend.commands import runmeta

    meta = _resume_meta()
    meta[field] = value
    run_dir = _run_dir(tmp_path, meta)

    def namespace_must_not_be_constructed(**_kwargs):
        raise AssertionError("Namespace constructed before all saved shapes were validated")

    monkeypatch.setattr(runmeta.argparse, "Namespace", namespace_must_not_be_constructed)
    with pytest.raises(UsageError, match=field):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"timeout": 0}, "timeout"),
        ({"max_friends": 0}, "max-friends"),
        ({"max_calls": -1}, "max-calls"),
        ({"require_friends": 0}, "require-friends"),
        ({"max_rounds": 0}, "max-rounds"),
        ({"max_wall_clock": 0}, "max-wall-clock"),
        ({"max_loop_iterations": 0}, "max-loop-iterations"),
        ({"model": "--provider-flag"}, "model"),
        ({"roster": ""}, "roster"),
        ({"roster": "bad\x00path"}, "roster"),
        ({"artifact": ""}, "artifact"),
        ({"artifact": "bad\x00path"}, "artifact"),
        ({"mode": "crossexam", "max_rounds": 1}, "judging round"),
        (
            {"enable_provider": ["codex"], "disable_provider": ["codex"]},
            "both --enable-provider and --disable-provider",
        ),
    ],
)
def test_saved_invocation_semantics_are_rejected_before_namespace(
    monkeypatch, tmp_path, changes, error
):
    from afriend.commands import runmeta

    meta = _resume_meta()
    meta["invocation"].update(changes)
    run_dir = _run_dir(tmp_path, meta)

    def namespace_must_not_be_constructed(**_kwargs):
        raise AssertionError("Namespace constructed before invocation semantics were validated")

    monkeypatch.setattr(runmeta.argparse, "Namespace", namespace_must_not_be_constructed)
    with pytest.raises(UsageError, match=error):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("timeout", 0, "timeout"),
        ("model", "--provider-flag", "model"),
        ("name", "../escape", "friend name"),
        ("cli", "", "required key: cli"),
        ("lens", "", "required key: lens"),
        ("scope", "outside", "scope"),
    ],
)
def test_saved_roster_semantics_are_rejected_before_friendspec(
    monkeypatch, tmp_path, field, value, error
):
    from afriend.commands import runmeta

    meta = _resume_meta()
    meta["roster"][0][field] = value
    run_dir = _run_dir(tmp_path, meta)

    def friendspec_must_not_be_constructed(**_kwargs):
        raise AssertionError("FriendSpec constructed before roster semantics were validated")

    monkeypatch.setattr(runmeta, "FriendSpec", friendspec_must_not_be_constructed)
    with pytest.raises(UsageError, match=error):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize("mode", ["report", "crossexam"])
def test_saved_roster_uniqueness_is_checked_before_friendspec(monkeypatch, tmp_path, mode):
    from afriend.commands import runmeta

    meta = _resume_meta()
    first = meta["roster"][0]
    second = dict(first)
    if mode == "report":
        second["lens"] = "security"
    else:
        second["name"] = "fake-ops-1"
    meta["roster"] = [first, second]
    meta["invocation"]["mode"] = mode
    run_dir = _run_dir(tmp_path, meta)

    def friendspec_must_not_be_constructed(**_kwargs):
        raise AssertionError("FriendSpec constructed before roster uniqueness was validated")

    monkeypatch.setattr(runmeta, "FriendSpec", friendspec_must_not_be_constructed)
    with pytest.raises(UsageError, match=r"duplicate friend name|same friend"):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spent_calls", -1),
        ("attempted_calls", -1),
        ("iterations_run", -1),
        ("rounds_run", -1),
        ("dry_streak", -1),
        ("resume_iteration", 0),
        ("active_elapsed_s", -1),
        ("required_friends", 0),
    ],
)
def test_checkpoint_numeric_semantics_are_rejected_before_namespace(
    monkeypatch, tmp_path, field, value
):
    from afriend.commands import runmeta

    meta = _resume_meta()
    meta[field] = value
    run_dir = _run_dir(tmp_path, meta)

    def namespace_must_not_be_constructed(**_kwargs):
        raise AssertionError("Namespace constructed before checkpoint semantics were validated")

    monkeypatch.setattr(runmeta.argparse, "Namespace", namespace_must_not_be_constructed)
    with pytest.raises(UsageError, match=field):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize("lifecycle", [None, "running", "terminal"])
def test_current_schema_requires_waiting_lifecycle_before_namespace(
    monkeypatch, tmp_path, lifecycle
):
    from afriend.commands import runmeta

    meta = validated_meta(_resume_meta())
    if lifecycle is None:
        meta.pop("lifecycle_state", None)
    else:
        meta["lifecycle_state"] = lifecycle
    run_dir = _run_dir(tmp_path, meta)

    def namespace_must_not_be_constructed(**_kwargs):
        raise AssertionError("Namespace constructed before lifecycle was validated")

    monkeypatch.setattr(runmeta.argparse, "Namespace", namespace_must_not_be_constructed)
    with pytest.raises(UsageError, match="waiting-for-orchestrator"):
        runmeta._restore_args(_resume_args(run_dir))


@pytest.mark.parametrize(
    "snapshot",
    [
        {
            "repo_root": None,
            "commit": None,
            "tree": None,
            "artifact_path": "",
            "artifact_hash": "",
            "predecessor": None,
        },
        {
            "repo_root": None,
            "commit": None,
            "tree": None,
            "artifact_path": "artifact/spec.md",
            "artifact_hash": "not-a-sha256",
            "predecessor": None,
        },
    ],
)
def test_snapshot_semantics_are_rejected_before_namespace(monkeypatch, tmp_path, snapshot):
    from afriend.commands import runmeta

    meta = _resume_meta()
    meta["snapshot"] = snapshot
    meta["snapshot_history"] = [snapshot]
    run_dir = _run_dir(tmp_path, meta)

    def namespace_must_not_be_constructed(**_kwargs):
        raise AssertionError("Namespace constructed before snapshot semantics were validated")

    monkeypatch.setattr(runmeta.argparse, "Namespace", namespace_must_not_be_constructed)
    with pytest.raises(UsageError, match="snapshot"):
        runmeta._restore_args(_resume_args(run_dir))


def test_deep_metadata_is_rejected_before_copying():
    raw: dict[str, object] = {}
    cursor = raw
    for _ in range(500):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child

    with pytest.raises(UsageError, match="metadata bound"):
        validated_meta(raw)

    assert "schema_version" not in raw


def test_wide_metadata_is_rejected_without_mutating_input():
    values = list(range(9_000))
    raw = {"wide": values}

    with pytest.raises(UsageError, match="metadata bound"):
        validated_meta(raw)

    assert raw == {"wide": values}


def test_the_current_fixtures_carry_the_current_schema_version():
    """The fixtures named `run_meta_current_*` must actually be current.

    They are the only committed examples of a readable run.json, so a stale
    version in them means every test that loads one is exercising a shape
    the code refuses -- or, worse, one it happens to still accept while
    meaning something different by it.
    """
    fixtures = Path(__file__).resolve().parent / "fixtures"
    found = sorted(fixtures.glob("run_meta_current_*.json"))
    assert found, "expected committed current-schema fixtures"
    for path in found:
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["schema_version"] == CURRENT_SCHEMA_VERSION, path.name
        # And the fixture must survive the real validator, not just match
        # the integer.
        assert validated_meta(meta)["schema_version"] == CURRENT_SCHEMA_VERSION


def test_a_previous_schema_version_is_refused_by_version_not_by_content():
    """The failure a version bump buys.

    `successful_friend_ids` changed meaning without the version moving, so a
    0.10.3 run.json still validated and then failed resume with "saved
    successful_friend_ids disagrees with the friend audit rows" -- a
    content complaint about a version difference, pointing the operator at
    the wrong thing entirely. Refusing on the version says what actually
    happened.
    """
    fixtures = Path(__file__).resolve().parent / "fixtures"
    meta = json.loads((fixtures / "run_meta_current_halted.json").read_text(encoding="utf-8"))
    meta["schema_version"] = CURRENT_SCHEMA_VERSION - 1

    with pytest.raises(UsageError, match="not readable by this version"):
        validated_meta(meta)
