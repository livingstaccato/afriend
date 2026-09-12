"""A failure has to name its own cause.

`finish_run` wrapped the metadata size bound and `RunOutcome.apply` in one
handler, so RunOutcome's own validation errors -- a structurally invalid or
non-JSON-safe `repeat_tracker`, say -- were reported as "this run's metadata
exceeds the bound run.json is written under" and prescribed "narrow the
roster or lower --max-loop-iterations". Wrong cause, and a remedy that
cannot help. Both still have to be caught: a bare traceback out of cli.main
discards the terminal run.json and report.md after the review is paid for.
"""

from afriend.commands.runmeta import _bound_exceeded


def test_the_bound_message_names_the_bound_and_its_remedy():
    message = _bound_exceeded(ValueError("too many nodes"))
    assert "exceeds the bound run.json is written under" in message
    assert "too many nodes" in message
    assert "narrow the roster" in message
    assert "ledger on disk are intact" in message


def test_an_invalid_run_state_is_not_reported_as_a_size_limit():
    """The distinction the split buys, asserted on the strings themselves so
    it survives a refactor of where they are raised."""
    from afriend.commands import runmeta

    source = runmeta.finish_run.__code__.co_consts
    flattened = " ".join(str(c) for c in source if isinstance(c, str))

    assert "this run's outcome could not be recorded" in flattened
    assert "invalid run state rather than a size limit" in flattened
    assert "will not change it" in flattened
