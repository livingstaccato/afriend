"""Focused report coverage for review completeness and unconfined-read warnings."""

from report_helpers import meta

from afriend.report import render as render_review
from afriend.reviewstate import ReviewState


def render(claims, aliases, run_meta):
    """Match the core report suite's replayed-state rendering helper."""
    return render_review(ReviewState.replay([*claims, *aliases]), run_meta)


def test_report_explains_that_zero_answers_provide_no_artifact_conclusion():
    out = render(
        [],
        [],
        meta(
            friends=[
                {
                    "name": "codex-security",
                    "independent": True,
                    "model": None,
                    "effort": None,
                    "round": 1,
                    "status": "failed: DNS temporary failure",
                }
            ]
        ),
    )

    assert "## Review completeness" in out
    assert "review incomplete: 0/1 friends answered; codex-security: DNS temporary failure" in out
    assert "no artifact conclusion follows from zero friend answers" in out.lower()
    assert out.index("## Review completeness") < out.index("## Friends")


def test_read_exposed_names_are_stably_deduplicated():
    repeated = {
        "name": "claude-security",
        "model": None,
        "effort": None,
        "transport": "exec",
        "write_protected": True,
        "declared_scope": "repo",
        "os_confined": False,
        "status": "ok",
    }
    out = render([], [], meta(friends=[dict(repeated, round=1), dict(repeated, round=2)]))
    sentence = next(line for line in out.splitlines() if line.startswith("**Filesystem"))
    assert sentence.count("claude-security") == 1
    assert "not recorded as OS-confined" in sentence
    assert "If started" in sentence
    assert "same-user filesystem read access" in sentence


def test_read_scope_does_not_claim_a_failed_before_launch_friend_ran_unconfined():
    friend = {
        "name": "claude-security",
        "model": None,
        "effort": None,
        "transport": "exec",
        "write_protected": True,
        "declared_scope": "repo",
        "os_confined": False,
        "status": "failed: refused before launch",
        "round": 1,
    }

    out = render([], [], meta(friends=[friend]))
    sentence = next(line for line in out.splitlines() if line.startswith("**Filesystem"))

    assert "not recorded as OS-confined" in sentence
    assert "If started, each retained same-user filesystem read access" in sentence
    assert "ran without OS confinement" not in sentence


def test_the_friend_that_lost_every_protection_is_still_named_as_read_exposed():
    """The withdrawal dropped the fully-unprotected friend out of the warning.

    The section was gated on `write_protected and not os_confined`. Once
    dispatch withdrew `readonly` for a skipped sandbox, agy and codex under
    `--allow-unsandboxed-friend` reported `write_protected: false` and fell
    out of the list -- while claude, write-protected and never confined,
    stayed in it. The friend that lost EVERY protection read as safer than
    one with partial protection. Read exposure is decided by confinement
    alone; write protection is irrelevant to what a process may open.
    """
    unprotected = {
        "name": "codex-security",
        "model": None,
        "effort": None,
        "transport": "exec",
        "write_protected": False,
        "declared_scope": "repo",
        "os_confined": False,
        "status": "ok",
        "round": 1,
    }

    out = render([], [], meta(friends=[unprotected]))
    sentence = next(line for line in out.splitlines() if line.startswith("**Filesystem"))

    assert "codex-security" in sentence
    # And the prose must not assert the property these friends do not have.
    assert "write-protected" not in sentence


def test_an_http_friend_is_never_named_as_read_exposed():
    """It is a bare model behind an endpoint: no subprocess, no filesystem."""
    http_friend = {
        "name": "ollama-ops",
        "model": "llama",
        "effort": None,
        "transport": "http",
        "write_protected": False,
        "declared_scope": "doc",
        "os_confined": False,
        "status": "ok",
        "round": 1,
    }

    out = render([], [], meta(friends=[http_friend]))

    assert not [line for line in out.splitlines() if line.startswith("**Filesystem")]
