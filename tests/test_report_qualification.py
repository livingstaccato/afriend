"""What the report may and may not claim about a roster's evidence.

A policy name is a compressed claim about independence, and the compression
is where overclaiming hides. `distinct-sessions` in particular verifies
nothing beyond an invariant the runner already enforces -- roster names are
unique because they become output paths -- so a report that prints the policy
name and stops has told the reader that something was checked when nothing
was. Each policy therefore states its own limit next to its result.
"""

from report_helpers import claim, meta

from afriend.report import render as render_review
from afriend.reviewstate import ReviewState


def _render(policy: str, *, qualified: bool = True, families: list[str] | None = None) -> str:
    run_meta = meta()
    run_meta["qualification"] = {
        "policy": policy,
        "qualified": qualified,
        "qualifying_names": ["a", "b"],
        "provider_families": families if families is not None else ["codex"],
        "reason": None,
    }
    return render_review(ReviewState.replay([claim("c-0001@1", "low")]), run_meta)


def test_distinct_sessions_states_what_it_did_not_compare():
    text = _render("distinct-sessions")

    assert "qualified" in text
    assert "provider family and model were not compared" in text


def test_cross_provider_states_that_models_were_not_compared():
    text = _render("cross-provider", families=["codex", "claude"])

    assert "model identities were not compared" in text


def test_distinct_models_does_not_claim_a_verified_backend():
    text = _render("distinct-models")

    assert "requested model" in text
    assert "backend model verified" not in text


def test_alternative_policy_success_is_not_called_cross_provider():
    text = _render("distinct-sessions")

    assert "not cross-provider" in text


def test_cross_provider_success_carries_no_alternative_policy_caveat():
    text = _render("cross-provider", families=["codex", "claude"])

    assert "not cross-provider" not in text


def test_a_run_without_qualification_renders_no_section():
    run_meta = meta()
    text = render_review(ReviewState.replay([claim("c-0001@1", "low")]), run_meta)

    assert "## Qualification" not in text


def test_a_malformed_qualification_renders_no_section():
    run_meta = meta()
    run_meta["qualification"] = "nonsense"
    text = render_review(ReviewState.replay([claim("c-0001@1", "low")]), run_meta)

    assert "## Qualification" not in text
