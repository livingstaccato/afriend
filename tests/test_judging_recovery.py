import json
import threading

import pytest

from afriend import reviewcompleteness, rounds as rounds_mod
from afriend.adapters import Capability, FriendSpec
from afriend.authority import ExternalToolPolicy
from afriend.ceilings import Budget
from afriend.commands import checkpoint, crossexam as crossexam_mod
from afriend.commands.crossexam import run_rounds
from afriend.errors import UsageError
from afriend.judgebatch import persist_judging_batch, recover_judging_batch
from afriend.ledger import Claim, Verdict
from afriend.normalize import NormalizeResult
from afriend.reviewstate import ReviewState
from afriend.rounds import persist_result
from afriend.runstore import RunStore
from afriend.spawn import SpawnResult
from afriend.verdicts import build_successor


def _spec(name: str, lens: str) -> FriendSpec:
    return FriendSpec(name, "fake", lens, None, None, "doc", 30)


def _host_spec() -> FriendSpec:
    return FriendSpec(
        "codex-ops-0",
        "codex",
        "ops",
        None,
        None,
        "doc",
        30,
        independent=False,
        host_self_review=True,
    )


def _claim() -> Claim:
    return Claim(
        id="c-0001@1",
        supersedes=None,
        origin=["other/ops"],
        lens="ops",
        round=1,
        advisory=False,
        severity="high",
        claim="guard missing",
        location="src/a.py:1",
        evidence="evidence",
        failure_scenario="failure",
        suggested_fix="fix",
    )


def _vote(claim_id: str, verdict: str = "upheld", amended: str | None = None) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "verdict": verdict,
        "confidence": "high",
        "evidence_assessment": "verified",
        "reasoning": f"{verdict} {claim_id}",
        "counter_evidence": None,
        "amended_claim": amended,
    }


def _spawn(votes: list[dict[str, object]]) -> SpawnResult:
    return SpawnResult(
        argv=["fake"],
        exit_code=0,
        stdout="captured",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        result=NormalizeResult({"verdicts": votes}, [], True),
        failure_reason=None,
        orphans_suspected=False,
    )


def _judge_for_real(monkeypatch, store, specs, claims, artifact, votes_for, round_no, **kwargs):
    """Produce a run directory by RUNNING the judging round, not by hand.

    A version-2 batch binds the judge identity, the round, the prompt bytes
    and the parsed capture by digest, so a fixture cannot assemble one that
    survives `recover_judging_batch` -- the prompt is rebuilt at resume from
    the artifact and the slice, and only a prompt the round actually wrote
    will match.

    That binding is the point. Since crossexam persists the batch BEFORE the
    first `store.ledger.append`, a ledger verdict with no batch behind it is
    unreachable in a real run, and resume now refuses it rather than letting
    it suppress a judge.
    """

    def dispatch(dispatched_specs, *_args, **_kwargs):
        return rounds_mod.DispatchRoundOutcome(
            [
                (
                    spec,
                    Capability(False, True, "none"),
                    _spawn(votes_for[spec.name]),
                    ExternalToolPolicy.DENY,
                )
                for spec in dispatched_specs
                if spec.name in votes_for
            ]
        )

    monkeypatch.setattr(crossexam_mod, "dispatch_round", dispatch)
    return run_rounds(
        specs,
        claims,
        store,
        ReviewState.replay(store.ledger.records()),
        {},
        None,
        artifact.parent / "schema.json",
        artifact,
        artifact.read_text(),
        None,
        None,
        threading.Event(),
        Budget(max_calls=20, started=0.0),
        round_no,
        now=lambda: 0.0,
        **kwargs,
    )


def _rewrite_audit_version(store: RunStore, spec: FriendSpec, version: int) -> dict[str, object]:
    path = store.friend_audit_path(2, spec.name)
    data = json.loads(path.read_text())
    if version == 2:
        persist_judging_batch(store, 2, spec, data["row"], [], [], [])
        data = json.loads(path.read_text())
    return data


@pytest.mark.parametrize("version", [1, 2])
def test_judging_sidecar_recovery_injects_frozen_advisory_host_role(tmp_path, version):
    spec = _host_spec()
    store = RunStore(tmp_path, f"run-host-role-v{version}")
    store.write_sensitive(store.friend_prompt_path(2, spec.name), "judge prompt")
    persist_result(
        store,
        2,
        spec,
        Capability(False, True, "none"),
        SpawnResult(
            argv=["codex"],
            exit_code=0,
            stdout="{}",
            stderr="",
            duration_s=0.1,
            timed_out=False,
            result=NormalizeResult({}, [], True),
            failure_reason=None,
            orphans_suspected=False,
        ),
        "exec",
        ExternalToolPolicy.DENY,
    )
    data = _rewrite_audit_version(store, spec, version)
    data["row"].pop("independent")
    data["row"].pop("host_self_review")
    store.write_sensitive_atomic(
        store.friend_audit_path(2, spec.name), json.dumps(data, sort_keys=True)
    )

    recovered = rounds_mod.recover_result_audit(store, 2, spec)

    assert recovered["independent"] is False
    assert recovered["host_self_review"] is True


@pytest.mark.parametrize("version", [1, 2])
def test_judging_sidecar_recovery_rejects_role_conflicting_with_frozen_host(tmp_path, version):
    spec = _host_spec()
    store = RunStore(tmp_path, f"run-host-role-conflict-v{version}")
    store.write_sensitive(store.friend_prompt_path(2, spec.name), "judge prompt")
    persist_result(
        store,
        2,
        spec,
        Capability(False, True, "none"),
        SpawnResult(
            argv=["codex"],
            exit_code=0,
            stdout="{}",
            stderr="",
            duration_s=0.1,
            timed_out=False,
            result=NormalizeResult({}, [], True),
            failure_reason=None,
            orphans_suspected=False,
        ),
        "exec",
        ExternalToolPolicy.DENY,
    )
    data = _rewrite_audit_version(store, spec, version)
    data["row"]["independent"] = True
    store.write_sensitive_atomic(
        store.friend_audit_path(2, spec.name), json.dumps(data, sort_keys=True)
    )

    with pytest.raises(UsageError, match="independent conflicts with the frozen roster"):
        rounds_mod.recover_result_audit(store, 2, spec)


def test_judging_retry_reuses_durable_verdicts_and_dispatches_only_missing_work(
    monkeypatch, tmp_path
):
    """Only the judge that has not voted is dispatched again.

    The durable half is built by running the round, because that is the only
    way to get the version-2 batch a resume now requires before it will let a
    ledger verdict suppress a judge. Hand-assembling ledger verdicts with no
    batch behind them used to work here, and that was the vulnerability:
    crossexam persists the batch before it appends, so no real run can reach
    that state -- only a writer into the run directory.
    """
    first = _spec("first-ops-0", "first")
    second = _spec("second-ops-0", "second")
    claim = _claim()
    store = RunStore(tmp_path, "run-recover-judging")
    store.ledger.append(claim)
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# artifact\n")
    _judge_for_real(
        monkeypatch,
        store,
        [first, second],
        [claim],
        artifact,
        {first.name: [_vote(claim.id)]},
        2,
    )
    durable = next(
        record
        for record in store.ledger.records()
        if isinstance(record, Verdict) and record.judge == "fake/first"
    )
    dispatched: list[str] = []

    def dispatch(specs, *_args, **_kwargs):
        dispatched.extend(spec.name for spec in specs)
        return rounds_mod.DispatchRoundOutcome(
            [
                (
                    second,
                    Capability(False, True, "none"),
                    _spawn([_vote(claim.id)]),
                    ExternalToolPolicy.DENY,
                )
            ]
        )

    monkeypatch.setattr(crossexam_mod, "dispatch_round", dispatch)
    budget = Budget(max_calls=10, started=0.0)
    outcome = run_rounds(
        [first, second],
        [claim],
        store,
        ReviewState.replay(store.ledger.records()),
        {},
        None,
        tmp_path / "schema.json",
        artifact,
        artifact.read_text(),
        None,
        None,
        threading.Event(),
        budget,
        2,
        now=lambda: 0.0,
    )

    assert dispatched == [second.name]
    assert list(store.ledger.verdicts_for(claim.id)) == [durable, outcome.verdicts[-1]]
    assert outcome.states[claim.id] == "settled-upheld"


@pytest.mark.parametrize("crash_on_append", [1, 2])
def test_judging_retry_replays_a_complete_captured_batch_without_redispatch(
    monkeypatch, tmp_path, crash_on_append
):
    spec = _spec("first-ops-0", "first")
    claims = [_claim(), Claim(**{**_claim().__dict__, "id": "c-0002@1"})]
    store = RunStore(tmp_path, f"run-complete-batch-{crash_on_append}")
    for claim in claims:
        store.ledger.append(claim)
    artifact = tmp_path / "artifact.md"
    artifact.write_text("artifact")
    payload = {
        "verdicts": [
            {
                "claim_id": claim.id,
                "verdict": "upheld",
                "confidence": "high",
                "evidence_assessment": "confirmed",
                "reasoning": f"checked {claim.id}",
                "counter_evidence": None,
                "amended_claim": None,
            }
            for claim in claims
        ]
    }
    result = SpawnResult(
        argv=["fake"],
        exit_code=0,
        stdout="captured",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        result=NormalizeResult(payload, [], True),
        failure_reason=None,
        orphans_suspected=False,
    )
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: rounds_mod.DispatchRoundOutcome(
            [(spec, Capability(False, True, "none"), result, ExternalToolPolicy.DENY)]
        ),
    )
    original_append = store.ledger.append
    verdict_appends = 0

    def crash_during_batch(record):
        nonlocal verdict_appends
        if isinstance(record, Verdict):
            verdict_appends += 1
            if verdict_appends == crash_on_append:
                raise RuntimeError("injected verdict append crash")
        original_append(record)

    monkeypatch.setattr(store.ledger, "append", crash_during_batch)
    with pytest.raises(RuntimeError, match="injected verdict append crash"):
        run_rounds(
            [spec],
            claims,
            store,
            ReviewState.replay(store.ledger.records()),
            {},
            None,
            tmp_path / "schema.json",
            artifact,
            "artifact",
            None,
            None,
            threading.Event(),
            Budget(max_calls=10, started=0.0),
            2,
            now=lambda: 0.0,
        )

    audit = store.friend_audit_path(2, spec.name)
    assert __import__("json").loads(audit.read_text())["version"] == 2
    monkeypatch.setattr(store.ledger, "append", original_append)
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: pytest.fail("captured batch was redispatched"),
    )
    budget = Budget(max_calls=10, started=0.0)
    outcome = run_rounds(
        [spec],
        claims,
        store,
        ReviewState.replay(store.ledger.records()),
        {},
        None,
        tmp_path / "schema.json",
        artifact,
        "artifact",
        None,
        None,
        threading.Event(),
        budget,
        2,
        now=lambda: 0.0,
    )

    assert [
        verdict.claim_id for verdict in store.ledger.records() if isinstance(verdict, Verdict)
    ] == [claim.id for claim in claims]
    assert budget.calls == 1
    assert [row["name"] for row in outcome.friends_meta] == [spec.name]


def test_judging_retry_reuses_a_successor_persisted_before_the_crash(monkeypatch, tmp_path):
    first = _spec("first-ops-0", "first")
    second = _spec("second-ops-0", "second")
    claim = _claim()
    verdicts = [
        Verdict(
            claim.id,
            f"fake/{lens}",
            2,
            "amended",
            "high",
            "verified",
            "rewrite it",
            None,
            "guard is conditionally missing",
        )
        for lens in ("first", "second")
    ]
    successor, _note = build_successor(claim, verdicts, 2)
    store = RunStore(tmp_path, "run-recover-successor")
    store.ledger.append(claim)
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# artifact\n")
    _judge_for_real(
        monkeypatch,
        store,
        [first, second],
        [claim],
        artifact,
        {
            first.name: [_vote(claim.id, "amended", "guard is conditionally missing")],
            second.name: [_vote(claim.id, "amended", "guard is conditionally missing")],
        },
        2,
    )
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: pytest.fail("durable judging work was redispatched"),
    )

    outcome = run_rounds(
        [first, second],
        [claim, successor],
        store,
        ReviewState.replay(store.ledger.records()),
        {},
        None,
        tmp_path / "schema.json",
        artifact,
        artifact.read_text(),
        None,
        None,
        threading.Event(),
        Budget(max_calls=10, started=0.0),
        2,
        now=lambda: 0.0,
    )

    assert [saved.id for saved in store.ledger.claims()] == [claim.id, successor.id]
    assert not any(saved.id.endswith("@3") for saved in outcome.claims)
    assert [row["transport"] for row in outcome.friends_meta] == ["fake", "fake"]


def test_recovered_verdict_refuses_a_tampered_audit_capture(monkeypatch, tmp_path):
    spec = _spec("first-ops-0", "first")
    claim = _claim()
    store = RunStore(tmp_path, "run-tampered-judge-audit")
    store.ledger.append(claim)
    artifact = tmp_path / "artifact.md"
    artifact.write_text("artifact")
    _judge_for_real(
        monkeypatch,
        store,
        [spec],
        [claim],
        artifact,
        {spec.name: [_vote(claim.id)]},
        2,
    )
    store.write_sensitive(store.friend_paths(2, spec.name)[0], "tampered")
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: pytest.fail("a tampered run was redispatched"),
    )

    with pytest.raises(UsageError, match="raw capture was modified"):
        run_rounds(
            [spec],
            [claim],
            store,
            ReviewState.replay(store.ledger.records()),
            {},
            None,
            tmp_path / "schema.json",
            artifact,
            artifact.read_text(),
            None,
            None,
            threading.Event(),
            Budget(max_calls=10, started=0.0),
            2,
            now=lambda: 0.0,
        )


def test_an_incomplete_judging_audit_fails_closed_instead_of_redispatching(monkeypatch, tmp_path):
    spec = _spec("first-ops-0", "first")
    claim = _claim()
    store = RunStore(tmp_path, "run-incomplete-audit")
    store.ledger.append(claim)
    store.write_sensitive(store.friend_prompt_path(2, spec.name), "captured prompt")
    result = SpawnResult(
        argv=["fake"],
        exit_code=0,
        stdout="captured but not committed",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        result=NormalizeResult({}, [], True),
        failure_reason=None,
        orphans_suspected=False,
    )
    persist_result(
        store,
        2,
        spec,
        Capability(False, True, "none"),
        result,
        "fake",
        ExternalToolPolicy.DENY,
    )
    artifact = tmp_path / "artifact.md"
    artifact.write_text("artifact")
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: pytest.fail("incomplete prior call was redispatched"),
    )

    with pytest.raises(UsageError, match="no authenticated complete verdict batch"):
        run_rounds(
            [spec],
            [claim],
            store,
            ReviewState.replay(store.ledger.records()),
            {},
            None,
            tmp_path / "schema.json",
            artifact,
            "artifact",
            None,
            None,
            threading.Event(),
            Budget(max_calls=10, started=0.0),
            2,
            now=lambda: 0.0,
        )


def test_judging_sidecar_verdict_tamper_disagrees_with_bound_parsed_batch(tmp_path):
    spec = _spec("first-ops-0", "first")
    claim = _claim()
    verdict = Verdict(
        claim.id, "fake/first", 2, "upheld", "high", "confirmed", "original", None, None
    )
    store = RunStore(tmp_path, "run-sidecar-verdict-tamper")
    store.write_sensitive(store.friend_prompt_path(2, spec.name), "prompt")
    result = SpawnResult(
        argv=["fake"],
        exit_code=0,
        stdout="raw",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        result=NormalizeResult({}, [], True),
        failure_reason=None,
        orphans_suspected=False,
    )
    row = persist_result(
        store,
        2,
        spec,
        Capability(False, True, "none"),
        result,
        "fake",
        ExternalToolPolicy.DENY,
    )
    persist_judging_batch(store, 2, spec, row, [claim.id], [], [verdict])
    audit = store.friend_audit_path(2, spec.name)
    data = json.loads(audit.read_text())
    data["judging"]["verdicts"][0]["reasoning"] = "tampered"
    audit.write_text(json.dumps(data))

    with pytest.raises(UsageError, match="parsed batch"):
        recover_judging_batch(store, 2, spec, [claim.id], "prompt")


def test_judging_replay_does_not_let_future_votes_rewrite_an_earlier_successor(
    monkeypatch, tmp_path
):
    """A durable round 3 can exist when run.json lagged the append-only
    ledger. Replaying round 2 must settle it from round-2 votes alone: future
    votes are not prior history and cannot change the successor it minted."""
    first = _spec("first-ops-0", "first")
    second = _spec("second-ops-0", "second")
    claim = _claim()
    store = RunStore(tmp_path, "run-future-judging")
    store.ledger.append(claim)
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# artifact\n")
    _judge_for_real(
        monkeypatch,
        store,
        [first, second],
        [claim],
        artifact,
        {
            first.name: [_vote(claim.id, "amended", "round two wording")],
            second.name: [_vote(claim.id, "amended", "round two wording")],
        },
        2,
    )
    successor = next(saved for saved in store.ledger.claims() if saved.id != claim.id)
    _judge_for_real(
        monkeypatch,
        store,
        [first, second],
        [claim, successor],
        artifact,
        {
            first.name: [_vote(successor.id, "amended", "future wording")],
            second.name: [_vote(successor.id, "amended", "future wording")],
        },
        3,
        first_round=3,
    )
    monkeypatch.setattr(
        crossexam_mod,
        "dispatch_round",
        lambda *_args, **_kwargs: pytest.fail("durable judging work was redispatched"),
    )

    outcome = run_rounds(
        [first, second],
        [claim, successor],
        store,
        ReviewState.replay(store.ledger.records()),
        {},
        None,
        tmp_path / "schema.json",
        artifact,
        artifact.read_text(),
        None,
        None,
        threading.Event(),
        Budget(max_calls=10, started=0.0),
        3,
        first_round=2,
        now=lambda: 0.0,
    )

    round_two = [
        record
        for record in store.ledger.records()
        if isinstance(record, Verdict) and record.round == 2
    ]

    assert successor in outcome.claims
    assert not any(saved.id.endswith("@3") for saved in outcome.claims)
    assert outcome.verdicts[:2] == round_two


def test_a_recovered_judge_row_does_not_contradict_the_verdicts_it_is_counted_with(tmp_path):
    """The fallback row must not claim an outcome the run did not observe --
    in either direction.

    A bare `ok` was wrong because it turned the absence of any record that a
    friend ran into a durable claim that it passed. Replacing it with
    `failed: no persisted audit for this friend` was the opposite
    fabrication, and on this path it is contradicted by the evidence that
    reaches it: both callers get here only for a judge whose verdicts were
    found in the durable ledger and are about to be seeded into the round.
    report.md would then attribute those verdicts to a friend its own
    friends table called failed, and `reviewcompleteness.from_friends` would
    count it as a non-answering independent friend.

    What is actually missing is the per-friend audit file, so that is what
    the status says, in the one shape `_validate_status` accepts.
    """
    spec = _spec("fake-ops-0", "ops")
    store = RunStore(tmp_path, "run-recovered-row")

    row = rounds_mod.recover_result_audit(store, 2, spec)

    assert not row["status"].startswith("failed"), row["status"]
    assert "no persisted audit row" in row["status"]
    assert "verdicts recovered from the ledger" in row["status"]

    # Counted as having answered, because it did.
    assert checkpoint._success_status(row["status"]) is True
    assert reviewcompleteness._terminal_status(row["status"]) == (True, None)
    assert checkpoint.any_friend_succeeded([row]) is True

    # And the row still survives the validator a later --resume runs it
    # through, rather than being a shape only this function can produce.
    normalized = checkpoint.normalize_friend_rows([row], {spec.name})
    assert normalized[0]["status"] == row["status"]
