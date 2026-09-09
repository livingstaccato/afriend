"""One ready provider, and what a judging run can still do with it.

Reported from a real session: a host with only codex ready was told
`crossexam cannot run. It needs two independent non-host friends`, and the
operator had to work out on their own that naming two codex friends by hand
would satisfy `distinct-sessions`. Nothing in the refusal said so, and
discovery could not have built that roster anyway -- it makes one friend per
provider. A policy this CLI ships, validates and documents was unreachable
through the CLI's own roster builder.
"""

import json
from pathlib import Path

import pytest

from afriend import adapters
from afriend.cliargs import build_parser
from afriend.commands import friends as friends_module
from afriend.errors import NoFriendsError
from afriend.providerconfig import ProviderPolicy, ProviderSetting
from afriend.readiness import HOST_ENV_MARKERS

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "afriend" / "assets" / "adapters"


@pytest.fixture
def only_codex(monkeypatch):
    """Exactly one ready provider, which is the whole point of this file."""
    registry = adapters.load_adapters(ADAPTER_DIR)
    monkeypatch.setattr(
        friends_module.providerconfig,
        "load",
        lambda *_a, **_k: ProviderPolicy(
            {name: ProviderSetting(enabled=name == "codex", model=None) for name in registry}
        ),
    )
    # A real, harmless executable: readiness runs a deny-argv capability probe
    # against whatever `which` returns, so a made-up path fails as
    # policy-blocked and the roster is empty for the wrong reason.
    monkeypatch.setattr(
        friends_module.shutil, "which", lambda name: "/bin/echo" if name == "codex" else None
    )
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    # Reproduce the reported session exactly: the host is claude, so claude is
    # host-excluded, and codex is the one ready provider. Every other marker
    # is cleared first -- the developer running this suite is themselves
    # inside an agent host, and an inherited CODEX_* marker would make codex
    # the host and leave the roster empty for an unrelated reason.
    for marker in HOST_ENV_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    return registry


def _args(tmp_path, *extra):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n")
    return build_parser().parse_args(["run", str(artifact), *extra])


def test_crossexam_still_refuses_a_sole_provider_under_the_default_policy(only_codex, tmp_path):
    """Nothing here weakens the default. Two sessions of one CLI share an
    account, a model and a failure mode, and `cross-provider` exists to say
    that is not independent evidence."""
    with pytest.raises(NoFriendsError) as excinfo:
        friends_module.roster_for_run(_args(tmp_path, "--mode", "crossexam"), only_codex, None, [])

    assert "cross-provider" in str(excinfo.value)


def test_the_refusal_names_the_policy_that_would_accept_this_roster(only_codex, tmp_path):
    """The missing sentence. The operator had every piece of what they needed
    except the name of the flag, and the error is built with the policy list
    already in hand."""
    with pytest.raises(NoFriendsError) as excinfo:
        friends_module.roster_for_run(_args(tmp_path, "--mode", "crossexam"), only_codex, None, [])
    message = str(excinfo.value)

    assert "--qualification-policy distinct-sessions" in message
    assert "--mode report" in message


def test_distinct_sessions_makes_a_sole_provider_dispatchable(only_codex, tmp_path):
    """The gap closed end to end: with the policy that accepts same-provider
    sessions, discovery now builds a roster that satisfies it."""
    resolved, _specs = friends_module.roster_for_run(
        _args(tmp_path, "--mode", "crossexam", "--qualification-policy", "distinct-sessions"),
        only_codex,
        None,
        [],
    )

    assert [spec.cli for spec in resolved.specs] == ["codex", "codex"]
    assert resolved.qualification is not None
    assert resolved.qualification.qualified is True


def test_the_second_session_is_recorded_as_weaker_evidence(only_codex, tmp_path):
    """Reachable is not the same as equivalent. A run that got its quorum
    from one provider has to say so, or the report reads as disagreement
    between two independent reviewers."""
    downgrades: list[str] = []
    friends_module.roster_for_run(
        _args(tmp_path, "--mode", "crossexam", "--qualification-policy", "distinct-sessions"),
        only_codex,
        None,
        downgrades,
    )

    assert any("codex" in note and "same provider" in note for note in downgrades)


def test_report_mode_does_not_pay_for_a_second_session(only_codex, tmp_path):
    """`report` needs no quorum, so fanning out would double the cost of
    every single-provider run to satisfy a rule that is not being applied."""
    resolved, _specs = friends_module.roster_for_run(
        _args(tmp_path, "--mode", "report", "--qualification-policy", "distinct-sessions"),
        only_codex,
        None,
        [],
    )

    assert len(resolved.specs) == 1


def test_the_default_policy_never_fans_out(only_codex, tmp_path):
    """Under `cross-provider` a second codex session cannot help, so building
    one would spend a friend to arrive at the same refusal."""
    with pytest.raises(NoFriendsError):
        friends_module.roster_for_run(_args(tmp_path, "--mode", "gate"), only_codex, None, [])


def test_the_fanned_roster_survives_a_round_trip_through_run_metadata(only_codex, tmp_path):
    """Two friends of one provider must stay two distinct names once written
    -- they become run-directory paths, and a collision would overwrite one
    friend's output with the other's."""
    resolved, _specs = friends_module.roster_for_run(
        _args(tmp_path, "--mode", "crossexam", "--qualification-policy", "distinct-sessions"),
        only_codex,
        None,
        [],
    )
    names = [spec.name for spec in resolved.specs]

    assert len(set(names)) == len(names)
    assert json.loads(json.dumps(names)) == names
