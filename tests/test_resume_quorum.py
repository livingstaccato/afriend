"""Critique quorum on resume, and hostile saved-friend rows (Task 6)."""

import json

import pytest
from test_run_end_to_end_orchestrator import (
    _halt,
    _respond,
    _resume,
    _run_dir,
    _run_json,
    _write_run_json,
)

from afriend.commands.checkpoint import normalize_resume_report_state
from afriend.errors import UsageError


def _remove_success_checkpoint(tmp_path):
    meta = _run_json(tmp_path)
    for field in ("successful_friend_ids", "succeeded_friends", "required_friends"):
        meta.pop(field, None)
    _write_run_json(tmp_path, meta)


@pytest.mark.parametrize(
    ("modes", "expected_exit", "expected_successes"),
    [
        (("good", "good"), 0, ["fake-good-0", "fake-good-1"]),
        (("good", "crash"), 12, ["fake-good-0"]),
    ],
)
def test_the_checkpoint_records_exact_critique_quorum(
    tmp_path, modes, expected_exit, expected_successes
):
    """This used to strip the field and assert it was reconstructed from the
    audit rows. The reconstruction is now a cross-check rather than a
    fallback, so the assertion is on what the run actually wrote."""
    halted = _halt(tmp_path, *modes, extra=("--require-friends", "2"))
    assert halted.returncode == 10, halted.stderr
    assert _run_json(tmp_path)["successful_friend_ids"] == expected_successes
    _respond(tmp_path, [])

    resumed = _resume(tmp_path)

    assert resumed.returncode == expected_exit, resumed.stderr
    assert _run_json(tmp_path)["successful_friend_ids"] == expected_successes


def test_a_zero_success_extraction_checkpoint_does_not_fail_open(tmp_path):
    halted = _halt(
        tmp_path,
        "offtopic",
        "crash",
        extra=("--require-friends", "2"),
    )
    assert halted.returncode == 10, halted.stderr
    request_path = _run_dir(tmp_path) / "round-1" / "REQUEST.json"
    data = json.loads(request_path.read_text())
    data["unparseable"][0]["findings"] = []
    (request_path.parent / "RESPONSE.json").write_text(json.dumps(data))

    resumed = _resume(tmp_path)

    assert resumed.returncode == 1, resumed.stderr
    assert _run_json(tmp_path)["successful_friend_ids"] == []


def test_quorum_survives_two_loop_halts_with_repeated_names(tmp_path):
    halted = _halt(
        tmp_path,
        "judge_uphold_a",
        "judge_uphold_b",
        mode="loop",
        extra=(
            "--max-rounds",
            "2",
            "--max-loop-iterations",
            "2",
            "--require-friends",
            "2",
        ),
    )
    assert halted.returncode == 10, halted.stderr
    _respond(tmp_path, [])

    halted_again = _resume(tmp_path)

    assert halted_again.returncode == 10, halted_again.stderr
    _respond(tmp_path, [], round_no=3)

    terminal = _resume(tmp_path)

    assert terminal.returncode == 11, terminal.stderr
    assert len(_run_json(tmp_path)["successful_friend_ids"]) == 2


def test_a_checkpoint_without_the_quorum_field_is_refused(tmp_path):
    """The field used to be optional, reconstructed from the audit rows when
    absent. A run.json this version wrote always has it, so its absence is a
    stripped field rather than an older run."""
    halted = _halt(tmp_path, "good")
    assert halted.returncode == 10, halted.stderr
    _remove_success_checkpoint(tmp_path)
    _respond(tmp_path, [])

    resumed = _resume(tmp_path)

    assert resumed.returncode == 2, resumed.stderr
    assert "successful_friend_ids is required" in resumed.stderr


def test_a_quorum_disagreeing_with_the_audit_rows_is_refused(tmp_path):
    """The audit row records the friend as failed. Promoting it in the saved
    quorum is how an edited run.json buys a participation floor it never met."""
    halted = _halt(tmp_path, "good", "crash", extra=("--require-friends", "2"))
    assert halted.returncode == 10, halted.stderr
    meta = _run_json(tmp_path)
    assert meta["successful_friend_ids"] == ["fake-good-0"]
    meta["successful_friend_ids"] = ["fake-good-0", "fake-crash-1"]
    meta["succeeded_friends"] = 2
    _write_run_json(tmp_path, meta)
    _respond(tmp_path, [])

    resumed = _resume(tmp_path)

    assert resumed.returncode == 2, resumed.stderr
    assert "disagrees with the friend audit rows" in resumed.stderr


@pytest.mark.parametrize(
    "friends",
    [
        [1],
        [{"name": 1, "model": None, "effort": None, "round": 1, "status": "ok"}],
        [{"name": "fake-good-0", "round": "1", "status": "ok"}],
        [{"name": "fake-good-0", "model": None, "effort": None, "round": 1}],
        [
            {
                "name": "fake-good-0",
                "model": [],
                "effort": None,
                "round": 1,
                "status": "ok",
            }
        ],
    ],
)
def test_malformed_saved_friend_rows_refuse_resume_without_mutating_artifacts(tmp_path, friends):
    halted = _halt(tmp_path, "good")
    assert halted.returncode == 10, halted.stderr
    meta = _run_json(tmp_path)
    meta["friends"] = friends
    _write_run_json(tmp_path, meta)
    meta_path = _run_dir(tmp_path) / "run.json"
    report_path = _run_dir(tmp_path) / "report.md"
    before_meta = meta_path.read_bytes()
    before_report = report_path.read_bytes()

    resumed = _resume(tmp_path)

    assert resumed.returncode == 2, resumed.stderr
    assert "saved friends" in resumed.stderr
    assert meta_path.read_bytes() == before_meta
    assert report_path.read_bytes() == before_report


def test_saved_downgrades_are_strictly_validated_and_restored_in_order():
    assert normalize_resume_report_state({"downgrades": ["first", "second", "first"]})[
        "downgrades"
    ] == ["first", "second"]


@pytest.mark.parametrize("value", ["not-a-list", [1], ["x" * 8193]])
def test_hostile_saved_downgrades_are_refused(value):
    with pytest.raises(UsageError, match="saved downgrades"):
        normalize_resume_report_state({"downgrades": value})
