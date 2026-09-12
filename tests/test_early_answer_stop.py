"""Waiting for a friend that has already answered (§11.3).

agy, on its error path, writes its JSON and then does not exit until its own
`--print-timeout` elapses. Measured across seven cross-examinations: eleven
successful runs exited about 2.5 seconds after the work they reported, and
three hangs exited at 906 seconds having reported 163, 372 and 482 -- seven
to twelve minutes of waiting for an answer already sitting in the pipe.
"""

import json
import sys
import time

import pytest

from afriend import envelopes, spawn
from afriend.envelopes import (
    TERMINAL_SCAN_BYTES,
    TERMINAL_SCAN_LINES,
    Envelope,
    answer_is_complete,
)

pytestmark = pytest.mark.process


JSON_PATH = Envelope(kind="json_path", path="response")
NDJSON = Envelope(kind="ndjson")


def test_a_complete_json_object_is_a_finished_answer():
    whole = json.dumps({"status": "ERROR", "response": "", "error": "timeout"})
    assert answer_is_complete(whole, JSON_PATH) is True


def test_a_half_written_object_is_not():
    """The pump delivers whatever the pipe has: a check that fired on a
    partial write would truncate the answer it exists to preserve."""
    whole = json.dumps({"status": "SUCCESS", "response": "a long answer"})
    assert answer_is_complete(whole[: len(whole) // 2], JSON_PATH) is False


def test_an_ndjson_friend_is_never_stopped_early():
    """codex and opencode stream events, and the answer is a LATER line --
    codex emits a schema-shaped progress message before its real findings.
    Stopping at the first complete object would cut off the thing being
    waited for."""
    progress = json.dumps({"type": "item.completed", "item": {"text": "working"}})
    assert answer_is_complete(progress, NDJSON) is False


def test_trailing_prose_after_the_object_is_not_a_finished_answer():
    """A json_path friend's contract is that stdout IS the object. Anything
    after it means this is not that shape, so the run waits as before."""
    assert answer_is_complete('{"a": 1}\nstill going', JSON_PATH) is False


def test_the_run_stops_waiting_for_a_process_that_has_answered_and_hung(tmp_path):
    """The behaviour, against a real process: it writes a complete object,
    then sleeps far past the runner's patience. Before this the run waited
    for the CLI's own deadline -- up to fifteen minutes for an answer it
    already had."""
    script = (
        "import json,sys,time;"
        "sys.stdout.write(json.dumps({'status':'ERROR','response':'',"
        "'error':'timeout waiting for response'}));"
        "sys.stdout.flush();"
        "time.sleep(60)"
    )
    started = time.monotonic()
    outcome = spawn.run_process(
        [sys.executable, "-c", script], None, 45, tmp_path, envelope=JSON_PATH
    )
    elapsed = time.monotonic() - started

    assert outcome.stopped_after_answer is True
    assert outcome.timed_out is False
    # It answered immediately; anything near the 45s deadline means the loop
    # waited for the process rather than for the answer.
    assert elapsed < 15, elapsed
    assert "timeout waiting for response" in outcome.stdout


@pytest.mark.slow
def test_a_process_that_never_answers_still_runs_to_the_deadline(tmp_path):
    """The stop is 'it has answered', not 'it has written something'. A
    friend still working must not be cut off because its output happens to
    parse."""
    script = "import sys,time;sys.stdout.write('working');sys.stdout.flush();time.sleep(60)"
    started = time.monotonic()
    outcome = spawn.run_process(
        [sys.executable, "-c", script], None, 3, tmp_path, envelope=JSON_PATH
    )
    assert outcome.stopped_after_answer is False
    assert outcome.timed_out is True
    assert time.monotonic() - started >= 3


def test_a_missing_working_directory_does_not_read_as_a_missing_binary(tmp_path):
    """Popen raises the same error for both, and calling it "binary not
    found" sends a reader hunting for a CLI that is installed."""
    outcome = spawn.run_process([sys.executable, "-c", "pass"], None, 5, tmp_path / "nope")
    assert outcome.failure_reason is not None
    assert "working directory not found" in outcome.failure_reason, outcome.failure_reason


def test_an_early_stopped_answer_is_not_reported_as_a_failure(tmp_path):
    """The stop must preserve the answer, not just arrive at it sooner.

    Breaking the wait loop is followed by a process-group sweep, so the exit
    code becomes the signal WE sent (-15). Reporting that as `exit -15`
    marked the friend failed and discarded a payload that had already
    normalized successfully -- turning agy's answer-then-hang path from a
    slow success into a fast failure, which is worse than the hang.

    The test above could not catch this: its payload was agy's ERROR object,
    which fails normalization anyway, so a discarded answer and a preserved
    one look identical.
    """
    answer = json.dumps(
        {
            "findings": [
                {
                    "severity": "high",
                    "claim": "a real finding",
                    "location": "x.py:1",
                    "evidence": "e",
                    "failure_scenario": "f",
                    "suggested_fix": "s",
                }
            ],
            "no_findings": None,
        }
    )
    payload = json.dumps({"status": "SUCCESS", "response": answer})
    script = (
        f"import sys,time;sys.stdout.write({json.dumps(payload)});sys.stdout.flush();time.sleep(60)"
    )
    outcome = spawn.run_process(
        [sys.executable, "-c", script], None, 45, tmp_path, envelope=JSON_PATH
    )
    assert outcome.stopped_after_answer is True
    assert outcome.result.succeeded is True
    assert outcome.failure_reason is None, outcome.failure_reason


AGY = Envelope(kind="ndjson", match_field="event", terminal_event="result")

RESULT = json.dumps({"event": "result", "result": {"response": "done"}})
PROGRESS = json.dumps({"event": "assistant", "message": "still thinking"})


def test_the_declared_terminal_event_ends_the_stream():
    assert answer_is_complete(PROGRESS + "\n" + RESULT + "\n", AGY) is True


def test_an_event_after_the_terminal_one_does_not_reopen_the_stream():
    """The bound this whole check exists to hold. agy writes `result` and
    then does not exit; anything it emits on the way out -- a trailing
    progress event, a flush -- used to hide the terminal event, because only
    the last line was ever parsed. The run then paid the full
    `--print-timeout`: seven to twelve minutes, the exact hang this file
    documents.
    """
    assert answer_is_complete(RESULT + "\n" + PROGRESS + "\n", AGY) is True


def test_a_non_json_banner_after_the_terminal_event_does_not_hide_it():
    """CLIs write to the same pipe on their way out. A deprecation notice or
    an ANSI-decorated banner is not an event, and must not read as one."""
    assert answer_is_complete(RESULT + "\nwarning: agy 2.1 is deprecated\n", AGY) is True


def test_a_stream_whose_last_event_is_not_terminal_is_not_finished():
    """The other half: `result` is what ends it, not "some parseable event
    arrived". Without this, every NDJSON friend is cut off at its first
    complete line -- codex's answer is a later event than its progress."""
    assert answer_is_complete(PROGRESS + "\n", AGY) is False


def test_an_envelope_declaring_no_terminal_event_never_stops_early():
    """opencode and codex declare none. Their streams end when the process
    ends, and guessing a terminal event for them would truncate answers."""
    assert answer_is_complete(RESULT + "\n", NDJSON) is False


def test_a_terminal_event_older_than_the_scan_window_is_not_found():
    """Deliberate, not an oversight. The window bounds the per-poll cost;
    past it, a `result` followed by hundreds of further events is not a
    stream that ended, it is a stream still running.
    """
    noise = "\n".join(PROGRESS for _ in range(TERMINAL_SCAN_LINES + 5))
    assert answer_is_complete(RESULT + "\n" + noise + "\n", AGY) is False


def test_the_check_does_not_read_more_of_the_buffer_as_it_grows(monkeypatch):
    """The docstring's claim, asserted. Scanning the whole buffer on every
    poll costs more the longer a friend runs, and this check fires on nearly
    every poll for NDJSON -- each line ends with `}`, so the cheap guard
    never rejects it.
    """
    seen: list[int] = []
    original = envelopes.strip_ansi
    monkeypatch.setattr(
        envelopes, "strip_ansi", lambda text: seen.append(len(text)) or original(text)
    )
    huge = (PROGRESS + "\n") * 20_000

    answer_is_complete(huge + RESULT + "\n", AGY)

    assert seen and max(seen) <= TERMINAL_SCAN_BYTES
    assert max(seen) < len(huge)
