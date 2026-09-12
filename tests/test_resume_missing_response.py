"""The message that tells an operator how to continue a halted run.

`orchestrator.read_response` was deleted along with its two tests --
`test_a_missing_response_says_what_to_do` and
`test_malformed_json_is_a_usage_error` -- but `commands/resume.py` still
raises the equivalent guidance. `grep -rn "no RESPONSE" tests/` found
nothing afterwards, so the one line that says how to unstick a halted run
could be reworded or lost without a single test failing. Deleting the
implementation is not the same as deleting the behaviour.
"""

from pathlib import Path

import pytest
from test_resume_crash_safety import _store

from afriend.commands.resume import _prepare_response
from afriend.errors import UsageError


def _round_dir(store) -> Path:
    return store.round_dir(1)


def test_a_missing_response_says_exactly_what_to_write_and_how_to_continue(tmp_path):
    store = _store(tmp_path, "run-missing-response")
    round_dir = _round_dir(store)

    with pytest.raises(UsageError) as caught:
        _prepare_response(
            store,
            round_dir,
            {},
            round_no=1,
            question="which of these is right?",
            request_digest="sha256:" + "0" * 64,
        )

    message = str(caught.value)
    # What is missing, and where.
    assert "no RESPONSE.json" in message
    assert str(round_dir) in message
    # Why the run stopped.
    assert "halted for orchestrator judgment" in message
    # The two things the operator has to do, in order.
    assert "REQUEST.json" in message
    assert "--resume" in message


def test_a_missing_response_with_a_checkpoint_is_a_different_failure(tmp_path):
    """A halted run and a run whose checkpoint disagrees with its disk are
    not the same problem, and must not print the same instruction: writing a
    RESPONSE.json would not fix the second one."""
    store = _store(tmp_path, "run-missing-response-checkpointed")
    round_dir = _round_dir(store)
    digest = "sha256:" + "0" * 64
    applied_response = {
        "version": 1,
        "round": 1,
        "question": "q",
        "request_sha256": digest,
        "sha256": digest,
        "records": [],
    }

    with pytest.raises(UsageError) as caught:
        _prepare_response(
            store,
            round_dir,
            {"applied_response": applied_response},
            round_no=1,
            question="q",
            request_digest=digest,
        )

    message = str(caught.value)
    # Which checkpoint complaint it is depends on how the saved record
    # disagrees, and that is covered in test_resume_response_checkpoint.py.
    # The invariant here is only that it is NOT the halted-run instruction:
    # writing a RESPONSE.json cannot fix a checkpoint that disagrees with
    # what is on disk, so telling the operator to do that sends them in the
    # wrong direction entirely.
    assert "cannot resume" in message
    assert "no RESPONSE.json" not in message
    assert "REQUEST.json" not in message
