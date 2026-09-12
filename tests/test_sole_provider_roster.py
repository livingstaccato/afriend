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
import sys

import pytest

from afriend import adapters
from afriend.cliargs import build_parser
from afriend.commands import friends as friends_module
from afriend.errors import NoFriendsError
from afriend.providerconfig import ProviderPolicy, ProviderSetting

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "afriend" / "assets" / "adapters"


def _echo(directory: Path) -> str:
    """A real, harmless executable that exits 0 and prints its arguments.

    Readiness runs a deny-argv capability probe against whatever `which`
    returns and needs exit 0 with the probe's own flags in the output, so a
    made-up path, or an interpreter that rejects those flags, fails as
    policy-blocked and the roster is empty for the wrong reason. Windows has
    no echo binary, so there it is a one-line batch file."""
    if sys.platform != "win32":
        return "/bin/echo"
    stub = directory / "echo.cmd"
    stub.write_text("@echo %*\r\n", encoding="ascii")
    return str(stub)


@pytest.fixture
def only_codex(monkeypatch, tmp_path):
    """Exactly one ready provider, which is the whole point of this file."""
    registry = adapters.load_adapters(ADAPTER_DIR)
    monkeypatch.setattr(
        friends_module.providerconfig,
        "load",
        lambda *_a, **_k: ProviderPolicy(
            {name: ProviderSetting(enabled=name == "codex", model=None) for name in registry}
        ),
    )
    echo = _echo(tmp_path)
    monkeypatch.setattr(
        friends_module.shutil, "which", lambda name: echo if name == "codex" else None
    )
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    # Reproduce the reported session: the host is claude, so claude is
    # host-excluded and codex is the one ready provider. conftest's autouse
    # `_isolate_host_env` has already cleared every other marker.
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
    one would spend a friend to arrive at the same refusal.

    Asserted on the roster rather than only on the exception: the refusal
    holds whether or not fan-out happened, so a regression that doubled the
    provider spend would have left this test green.
    """
    args = _args(tmp_path, "--mode", "gate")

    assert friends_module._sessions_needed(args) == 1
    with pytest.raises(NoFriendsError) as excinfo:
        friends_module.roster_for_run(args, only_codex, None, [])
    assert "workers (codex-assumptions)" in str(excinfo.value)


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


@pytest.fixture
def codex_host_and_claude(monkeypatch, tmp_path):
    """The layout most operators actually have: codex hosting the session
    (advisory, non-independent) and exactly one other ready provider."""
    registry = adapters.load_adapters(ADAPTER_DIR)
    echo = _echo(tmp_path)
    monkeypatch.setattr(
        friends_module.providerconfig,
        "load",
        lambda *_a, **_k: ProviderPolicy(
            {
                name: ProviderSetting(enabled=name in {"codex", "claude"}, model=None)
                for name in registry
            }
        ),
    )
    monkeypatch.setattr(
        friends_module.shutil,
        "which",
        lambda name: echo if name in {"codex", "claude"} else None,
    )
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    return registry


def test_an_advisory_host_does_not_count_towards_the_two_sessions(codex_host_and_claude, tmp_path):
    """The dead end the first version of this shipped with.

    The fan-out gate counted DISCOVERED PROVIDERS, and a codex host is
    discovered -- as advisory host self-review, which `qualify` does not count
    as a worker. So this layout saw two providers, skipped the fan-out, and
    refused; the refusal advised `--qualification-policy distinct-sessions`;
    that run refused too, for a different reason, with the advice gone. The
    operator loops. The gate has to count independent workers.
    """
    resolved, _specs = friends_module.roster_for_run(
        _args(tmp_path, "--mode", "crossexam", "--qualification-policy", "distinct-sessions"),
        codex_host_and_claude,
        None,
        [],
    )
    workers = [s for s in resolved.specs if s.independent and not s.host_self_review]

    assert [s.cli for s in workers] == ["claude", "claude"]
    assert resolved.qualification is not None and resolved.qualification.qualified is True


def test_a_restricted_lens_list_is_not_told_to_switch_policy(only_codex, tmp_path):
    """`--lens assumptions` leaves nothing to fan out to, because a second
    session needs a second lens to be named with. Advising the policy flag
    here sends the operator to an identical refusal."""
    with pytest.raises(NoFriendsError) as excinfo:
        friends_module.roster_for_run(
            _args(tmp_path, "--mode", "crossexam", "--lens", "assumptions"),
            only_codex,
            None,
            [],
        )
    message = str(excinfo.value)

    assert "--qualification-policy distinct-sessions" not in message
    assert "lens" in message


def test_a_repeated_lens_does_not_abort_the_run(only_codex, tmp_path):
    """`--lens` is an append action with no dedup. Fanning across
    `lenses[1:]` turned a repeat into two friends with one name, and names
    become run-directory paths -- so a run that used to resolve one friend
    started dying with a duplicate-name UsageError naming nothing the
    operator typed."""
    resolved, _specs = friends_module.roster_for_run(
        _args(
            tmp_path,
            "--mode",
            "crossexam",
            "--qualification-policy",
            "distinct-sessions",
            "--lens",
            "assumptions",
            "--lens",
            "assumptions",
            "--lens",
            "security",
        ),
        only_codex,
        None,
        [],
    )

    assert [s.name for s in resolved.specs] == ["codex-assumptions", "codex-security"]


def test_an_explicit_same_provider_roster_is_disclosed_too(only_codex, tmp_path):
    """The documented workaround, which had no disclosure at all: the note
    was wired into the discovery branch, and --friend replaces discovery."""
    downgrades: list[str] = []
    friends_module.roster_for_run(
        _args(
            tmp_path,
            "--mode",
            "crossexam",
            "--qualification-policy",
            "distinct-sessions",
            "--friend",
            "codex:security",
            "--friend",
            "codex:ops",
        ),
        only_codex,
        None,
        downgrades,
    )

    assert any("same provider" in note for note in downgrades)


def test_capacity_trimming_does_not_leave_a_note_about_a_roster_that_is_gone(only_codex, tmp_path):
    """The note was appended before `apply_capacity`, so --max-friends=1 kept
    a sentence asserting two sessions while one survived."""
    downgrades: list[str] = []
    with pytest.raises(NoFriendsError):
        friends_module.roster_for_run(
            _args(
                tmp_path,
                "--mode",
                "crossexam",
                "--qualification-policy",
                "distinct-sessions",
                "--max-friends",
                "1",
            ),
            only_codex,
            None,
            downgrades,
        )

    assert not any("same provider" in note for note in downgrades)


def test_a_capacity_of_one_is_not_paid_for_twice(only_codex, tmp_path):
    """`--max-friends=1` cannot admit a second session, so building one and
    trimming it spends discovery on a spec that is discarded."""
    args = _args(
        tmp_path,
        "--mode",
        "crossexam",
        "--qualification-policy",
        "distinct-sessions",
        "--max-friends",
        "1",
    )

    assert friends_module._sessions_needed(args) == 1


def test_the_note_names_the_policy_actually_applied(only_codex, tmp_path):
    """The predicate is policy-agnostic -- two workers, one family -- so the
    text must not hardcode one policy's name. Under `distinct-models` the
    claim that they 'share a model' is also false."""
    downgrades: list[str] = []
    friends_module.roster_for_run(
        _args(
            tmp_path,
            "--mode",
            "crossexam",
            "--qualification-policy",
            "distinct-models",
            "--friend",
            "codex:security:gpt-5.4-a",
            "--friend",
            "codex:ops:gpt-5.4-b",
        ),
        only_codex,
        None,
        downgrades,
    )
    note = next(n for n in downgrades if "same provider" in n)

    assert "distinct-models" in note
    assert "distinct-sessions" not in note


def test_a_resumed_run_is_not_offered_remedies_that_cannot_apply(only_codex, tmp_path):
    """A resume replays a frozen qualification: the policy flag is ignored by
    design, and the roster cannot gain a friend. Printing both remedies tells
    the operator to do two things that provably change nothing."""
    args = _args(tmp_path, "--mode", "crossexam")
    # `fake` deliberately, not a real provider: `validate_resume_capabilities`
    # takes `which` as a DEFAULT ARGUMENT, bound to `shutil.which` at import,
    # so the fixture's patch cannot reach it. With a real cli this test passed
    # only on a machine that happened to have that binary installed, and CI
    # failed with "saved provider 'codex' is unavailable".
    spec = adapters.FriendSpec(
        name="fake-assumptions",
        cli="fake",
        lens="assumptions",
        model=None,
        effort=None,
        scope="doc",
        timeout=60,
    )
    args._resume_roster = [spec]
    args._resume_meta = {}

    with pytest.raises(NoFriendsError) as excinfo:
        friends_module.roster_for_run(args, only_codex, None, [])
    message = str(excinfo.value)

    assert "Options:" not in message
    assert "add a friend" not in message
    assert "resumed run replays" in message
