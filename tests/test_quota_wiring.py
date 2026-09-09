"""A quota failure has to travel, not just be recognised.

`classify` returning QUOTA is worth nothing on its own: the note has to
reach the round outcome, and from there the run's downgrades, or a roster
that quietly shrank looks like a roster that answered. That journey is the
part a unit test of `classify` cannot see, and it is where this kind of
change usually breaks.
"""

import threading

import pytest

from afriend.adapters import Capability, FriendSpec, load_adapters
from afriend.authority import ExternalToolPolicy
from afriend.failures import AUTH, QUOTA, RepeatTracker, classify
from afriend.normalize import NormalizeResult
from afriend.paths import ADAPTER_DIR
import afriend.rounds as rounds_mod
from afriend.runstore import RunStore
from afriend.spawn import SpawnResult

QUOTA_TEXT = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
    "to purchase more credits or try again at Sep 14th, 2026 6:51 PM."
)


def _spec(name: str, cli: str) -> FriendSpec:
    return FriendSpec(
        name=name, cli=cli, lens="ops", model=None, effort=None, scope="doc", timeout=60
    )


def _failure(*, provider_error: str | None = None, stderr: str = "") -> SpawnResult:
    return SpawnResult(
        argv=["codex"],
        exit_code=1,
        stdout="",
        stderr=stderr,
        duration_s=5.0,
        timed_out=False,
        result=NormalizeResult(payload=None, errors=["unusable output"], succeeded=False),
        failure_reason="exit 1",
        orphans_suspected=False,
        provider_error=provider_error,
    )


def _run_round(monkeypatch, tmp_path, outcome: SpawnResult):
    spec = _spec("codex-ops-0", "codex")

    def fake_dispatch(spec_arg, *_args, **_kwargs):
        return spec_arg, Capability(False, True, "none"), outcome, ExternalToolPolicy.DENY

    monkeypatch.setattr(rounds_mod, "_dispatch", fake_dispatch)
    store = RunStore(tmp_path, "run-quota")
    store.lock()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("REVIEW THIS")
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n")
    return rounds_mod.dispatch_round(
        [spec],
        1,
        {spec.name: prompt},
        store,
        {"codex": load_adapters(ADAPTER_DIR)["codex"]},
        None,
        tmp_path / "schema.json",
        artifact,
        None,
        None,
        threading.Event(),
        tracker=RepeatTracker(),
        max_concurrency=1,
    )


def test_a_quota_failure_reaches_the_round_outcome(monkeypatch, tmp_path):
    batch = _run_round(monkeypatch, tmp_path, _failure(provider_error=QUOTA_TEXT))

    assert len(batch.quota_notes) == 1
    assert "codex-ops-0" in batch.quota_notes[0]
    assert "reviewed nothing" in batch.quota_notes[0]


def test_a_quota_failure_does_not_abort_the_run(monkeypatch, tmp_path):
    """The distinction that matters: auth stops everything, a spent quota
    stops one friend. Aborting here would discard the friends that still
    have allowance."""
    batch = _run_round(monkeypatch, tmp_path, _failure(provider_error=QUOTA_TEXT))

    assert batch.auth_abort is None


def test_an_auth_failure_still_aborts_and_records_no_quota_note(monkeypatch, tmp_path):
    batch = _run_round(monkeypatch, tmp_path, _failure(stderr="401 Unauthorized"))

    assert batch.auth_abort is not None
    assert batch.quota_notes == ()


def test_an_ordinary_failure_records_neither(monkeypatch, tmp_path):
    batch = _run_round(monkeypatch, tmp_path, _failure(provider_error="disk full"))

    assert batch.auth_abort is None
    assert batch.quota_notes == ()


def test_the_status_prefers_the_provider_error_over_a_noisy_stderr(tmp_path):
    """The whole motivation, asserted on the audit row rather than on
    envelope_error in isolation.

    The real codex failure had BOTH: "Reading prompt from stdin..." on
    stderr and the quota sentence in its structured output. A rule that only
    reached for the provider error when stderr was empty would have changed
    nothing about that row, which is the row that sent me to the raw capture.
    """
    outcome = _failure(provider_error=QUOTA_TEXT, stderr="Reading prompt from stdin...")
    store = RunStore(tmp_path, "run-status")
    store.lock()

    status = rounds_mod.persist_result(
        store,
        1,
        _spec("codex-ops-0", "codex"),
        Capability(False, True, "none"),
        outcome,
        "exec",
        ExternalToolPolicy.DENY,
    )["status"]

    assert "usage limit" in status
    assert "Reading prompt from stdin" not in status


def test_codex_offers_no_model_alternatives_because_it_cannot_list_them(monkeypatch, tmp_path):
    """`_quota_alternatives` must not invent names for a CLI with no listing
    command, and must not shell out to one either -- the note falls back to
    the remediation prose."""
    calls: list[object] = []
    monkeypatch.setattr(rounds_mod, "_dispatch", rounds_mod._dispatch)
    import afriend.models as models_mod

    monkeypatch.setattr(models_mod, "list_models", lambda *a, **k: calls.append(a) or None)
    batch = _run_round(monkeypatch, tmp_path, _failure(provider_error=QUOTA_TEXT))

    assert calls == []
    assert "Models this provider reports" not in batch.quota_notes[0]
    assert "another provider" in batch.quota_notes[0]


@pytest.mark.parametrize("name", ["codex"])
def test_the_shipped_markers_match_the_captured_message(name):
    """Guards the marker itself: a reworded `provider_error_contains` would
    leave every quota failure classified UNKNOWN, and no test above would
    notice because they all supply the same text."""
    adapter = load_adapters(ADAPTER_DIR)[name]

    assert adapter.quota.declared() is True
    assert classify(_failure(provider_error=QUOTA_TEXT), adapter) == QUOTA
    assert classify(_failure(stderr="401 Unauthorized"), adapter) == AUTH


def test_the_full_text_pointer_names_the_file_that_holds_it(tmp_path):
    """Confirmed against a real run, not argued.

    A provider error is extracted from the CLI's structured STDOUT, so it
    lands in the .raw capture. The status pointed at the .err file, which in
    that run held `Reading prompt from stdin...` and an unrelated
    skills-extension error -- the quota sentence, and the reset date, were
    not in it. The misdirection this branch exists to end, one file along.
    """
    outcome = _failure(provider_error=QUOTA_TEXT, stderr="Reading prompt from stdin...")
    store = RunStore(tmp_path, "run-pointer")
    store.lock()

    status = rounds_mod.persist_result(
        store,
        1,
        _spec("codex-ops-0", "codex"),
        Capability(False, True, "none"),
        outcome,
        "exec",
        ExternalToolPolicy.DENY,
    )["status"]

    assert "round-1/codex-ops-0.raw" in status
    assert "round-1/codex-ops-0.err" not in status


def test_a_stderr_only_failure_still_points_at_the_stderr_capture(tmp_path):
    """The other branch must not follow it: an ordinary failure's diagnosis
    really is in .err."""
    store = RunStore(tmp_path, "run-pointer-2")
    store.lock()

    status = rounds_mod.persist_result(
        store,
        1,
        _spec("codex-ops-0", "codex"),
        Capability(False, True, "none"),
        _failure(stderr="something broke"),
        "exec",
        ExternalToolPolicy.DENY,
    )["status"]

    assert "round-1/codex-ops-0.err" in status


def test_a_round_without_a_repeat_tracker_still_classifies_its_failures(monkeypatch, tmp_path):
    """`tracker` is optional; classification is not. Nesting the verdicts
    inside `if tracker is not None` made a caller that passed none produce a
    roster that shrank in silence."""
    spec = _spec("codex-ops-0", "codex")
    outcome = _failure(provider_error=QUOTA_TEXT)

    def fake_dispatch(spec_arg, *_args, **_kwargs):
        return spec_arg, Capability(False, True, "none"), outcome, ExternalToolPolicy.DENY

    monkeypatch.setattr(rounds_mod, "_dispatch", fake_dispatch)
    store = RunStore(tmp_path, "run-no-tracker")
    store.lock()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("REVIEW THIS")
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n")

    batch = rounds_mod.dispatch_round(
        [spec],
        1,
        {spec.name: prompt},
        store,
        {"codex": load_adapters(ADAPTER_DIR)["codex"]},
        None,
        tmp_path / "schema.json",
        artifact,
        None,
        None,
        threading.Event(),
        max_concurrency=1,
    )

    assert len(batch.quota_notes) == 1
