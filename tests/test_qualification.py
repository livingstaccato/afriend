from dataclasses import replace

import pytest

from afriend.adapters import FriendSpec
from afriend.errors import UsageError
from afriend.qualification import QUALIFICATION_POLICIES, qualify


def _worker(name: str, cli: str, model: str | None, source: str = "explicit-friend") -> FriendSpec:
    return FriendSpec(name, cli, "ops", model, None, "doc", 30, model_source=source)


def test_cross_provider_requires_two_worker_provider_families():
    result = qualify(
        [_worker("codex-a", "codex", "gpt-a"), _worker("claude-a", "claude", "sonnet")],
        "cross-provider",
    )

    assert result.qualified is True
    assert result.qualifying_names == ("codex-a", "claude-a")


def test_same_provider_workers_need_an_explicit_alternative_policy():
    specs = [_worker("codex-a", "codex", "gpt-a"), _worker("codex-b", "codex", "gpt-a")]

    assert qualify(specs, "cross-provider").qualified is False
    assert qualify(specs, "distinct-sessions").qualified is True


def test_distinct_models_requires_different_concrete_requested_models():
    assert qualify(
        [_worker("a", "codex", "gpt-a"), _worker("b", "codex", "gpt-b")], "distinct-models"
    ).qualified
    assert not qualify(
        [_worker("a", "codex", "gpt-a"), _worker("b", "codex", None, "cli-default")],
        "distinct-models",
    ).qualified


def test_advisory_host_never_qualifies():
    advisory = replace(
        _worker("claude-host", "claude", "sonnet"), independent=False, host_self_review=True
    )

    assert not qualify(
        [_worker("codex-a", "codex", "gpt-a"), advisory], "distinct-sessions"
    ).qualified


@pytest.mark.parametrize("policy", QUALIFICATION_POLICIES)
def test_known_policy_is_accepted(policy: str):
    assert qualify([], policy).policy == policy


def test_unknown_policy_is_refused():
    with pytest.raises(UsageError, match="qualification policy"):
        qualify([], "invented")
