"""Model-selection provenance coverage for the report renderer."""

from report_helpers import claim, meta

from afriend.report import render as render_review
from afriend.reviewstate import ReviewState


def render(claims, aliases, run_meta):
    """Keep the focused renderer tests terse while exercising its state API."""
    return render_review(ReviewState.replay([*claims, *aliases]), run_meta)


def test_a_friend_row_without_a_model_source_is_not_mislabeled_as_inherited():
    m = meta(
        friends=[
            {
                "name": "friend-a",
                "model": None,
                "effort": None,
                "readonly": True,
                "scope": "repo",
                "status": "ok",
            },
        ]
    )
    out = render([claim("c-0001@1")], [], m)
    assert "| friend | role | independent | model | model source | effort |" in out
    assert "recorded model; selection source unavailable" in out
    assert "| friend-a | independent reviewer | True | inherited |" not in out
    assert "CLI default (no --model passed; exact model not verified)" not in out


def test_report_lists_persisted_model_selection_source():
    m = meta(
        friends=[
            {
                "name": "friend-a",
                "model": "gpt-6-astra",
                "model_source": "provider-setting",
                "effort": None,
                "readonly": True,
                "scope": "repo",
                "status": "ok",
            },
        ]
    )

    out = render([claim("c-0001@1")], [], m)

    assert "| friend-a | independent reviewer | True | gpt-6-astra | provider setting |" in out


def test_report_names_each_provider_when_a_cli_default_model_was_requested():
    m = meta(
        friends=[
            {
                "name": "codex-ops",
                "cli": "codex",
                "model": None,
                "model_source": "cli-default",
                "effort": None,
                "readonly": True,
                "scope": "repo",
                "status": "ok",
            },
            {
                "name": "opencode-ops",
                "cli": "opencode",
                "model": None,
                "model_source": "cli-default",
                "effort": None,
                "readonly": True,
                "scope": "repo",
                "status": "ok",
            },
        ]
    )

    out = render([claim("c-0001@1")], [], {**m, "external_tool_policy": "deny"})

    assert "Codex CLI default (no --model passed; exact model not verified)" in out
    assert "OpenCode CLI default (no --model passed; exact model not verified)" in out


def test_allowed_codex_report_does_not_claim_its_builtin_default():
    friend = {
        "name": "codex-ops",
        "cli": "codex",
        "model": None,
        "model_source": "cli-default",
        "effort": None,
        "readonly": True,
        "scope": "repo",
        "status": "ok",
    }
    denied = render(
        [claim("c-0001@1")],
        [],
        meta(friends=[friend], external_tool_policy="deny"),
    )
    allowed = render(
        [claim("c-0001@1")],
        [],
        meta(
            friends=[friend],
            external_tool_policy="scoped-allow",
            external_tool_grants=["codex"],
        ),
    )

    assert "Codex CLI default (no --model passed; exact model not verified)" in denied
    assert "Codex CLI default" not in allowed
    assert "user configuration may apply" in allowed
