"""Qualification evidence must survive the round trip through run metadata.

Three defects found by an adversarial review of the 0.8.0 plan, all in the
same seam: a policy is decided once, at admission, and everything afterwards
has to read that decision back rather than recompute it.

A run that was accepted stays accepted. Recomputing admission on resume makes
acceptance a function of the code version rather than of the run, so a run
recorded as qualified can stop being resumable because a default moved
underneath it.
"""

import pytest

from afriend.commands.runmeta import CURRENT_SCHEMA_VERSION
from afriend.errors import UsageError
from afriend.outcomes import RunOutcome, StopReason
from afriend.qualification import (
    restore_frozen_qualification,
)


def _terminal_outcome() -> RunOutcome:
    return RunOutcome(
        started_at="2026-09-08T00:00:00Z",
        finished_at="2026-09-08T00:00:01Z",
        duration_s=1.0,
        stop_reason=StopReason.COMPLETED,
        exit_code=0,
        converged=True,
        gate_decision=None,
        blocker_ids=(),
        ceiling_hit=None,
        attempted_calls=1,
        spent_calls=1,
        iterations_run=1,
        rounds_run=1,
        dry_streak=0,
        repeat_tracker={"last": {}, "count": {}, "disabled": {}},
    )


def test_terminal_metadata_keeps_the_current_schema_version():
    """`RunOutcome.apply` stamped a hardcoded 2 over the real version.

    Every completed run was therefore recorded as schema 2 regardless of the
    schema it was actually written with, so a later migration would treat a
    brand-new run as legacy and re-apply migrations it never needed.
    """
    base = {"schema_version": CURRENT_SCHEMA_VERSION, "lifecycle_state": "running"}

    applied = _terminal_outcome().apply(base)

    assert applied["schema_version"] == CURRENT_SCHEMA_VERSION
    assert applied["lifecycle_state"] == "terminal"


def _frozen(policy: str = "cross-provider", qualified: bool = True) -> dict[str, object]:
    return {
        "qualification": {
            "policy": policy,
            "qualified": qualified,
            "qualifying_names": ["a", "b"],
            "provider_families": ["codex", "claude"],
            "reason": None,
        }
    }


def test_a_frozen_qualification_is_replayed_verbatim():
    restored = restore_frozen_qualification(_frozen())

    assert restored is not None
    assert restored.policy == "cross-provider"
    assert restored.qualified is True
    assert restored.qualifying_names == ("a", "b")
    assert restored.provider_families == ("codex", "claude")


def test_a_frozen_unqualified_run_is_replayed_rather_than_re_refused():
    """The regression: a run recorded as not qualified still replays.

    Re-deciding admission on resume is what stranded runs. Whether the frozen
    verdict was positive or negative, resume reports what the run recorded.
    """
    restored = restore_frozen_qualification(_frozen(qualified=False))

    assert restored is not None
    assert restored.qualified is False


def test_absent_qualification_falls_back_to_fresh_admission():
    assert restore_frozen_qualification({}) is None
    assert restore_frozen_qualification({"qualification": None}) is None
    assert restore_frozen_qualification(None) is None


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"qualification": "nonsense"}, "must be an object"),
        ({"qualification": {"policy": "made-up", "qualified": True}}, "is not one of"),
        ({"qualification": {"policy": "cross-provider", "qualified": "yes"}}, "must be a boolean"),
        (
            {
                "qualification": {
                    "policy": "cross-provider",
                    "qualified": True,
                    "qualifying_names": [1, 2],
                }
            },
            "list of strings",
        ),
        (
            {
                "qualification": {
                    "policy": "cross-provider",
                    "qualified": True,
                    "reason": 7,
                }
            },
            "string or null",
        ),
    ],
)
def test_a_hostile_frozen_payload_is_refused(payload: dict[str, object], message: str):
    """Resume treats run.json as hostile input; replay does not soften that."""
    with pytest.raises(UsageError, match=message):
        restore_frozen_qualification(payload)
