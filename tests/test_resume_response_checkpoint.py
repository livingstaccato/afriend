"""The response-application checkpoint: durable before, exact after.

Applying an orchestrator response is two writes -- the ledger records and
the run.json checkpoint that says they happened -- plus the rename that
retires RESPONSE.json. These cover the order those must happen in, and what
each refuses when the bytes, the request binding, or the artifact on disk
disagrees with what was validated.

Split out of test_resume_crash_safety.py, whose helpers it shares.
"""

import hashlib
import json
from pathlib import Path
import threading

import pytest
from test_resume_crash_safety import (
    _args,
    _call_resume_round_one,
    _claim,
    _request_digest,
    _store,
)

from afriend import orchestrator
from afriend.ceilings import Budget
from afriend.commands.resume import resume_round_one
from afriend.errors import UsageError
from afriend.reviewstate import ReviewState


def test_response_application_checkpoint_is_durable_before_materialization(tmp_path, monkeypatch):
    store = _store(tmp_path, "run-checkpoint-before-rename")
    store.ledger.append(_claim(1, "defect A"))
    store.ledger.append(_claim(2, "defect A reworded"))
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [_claim(1), _claim(2)])
    response = {
        "version": 1,
        "merges": [{"canonical": "c-0001@1", "duplicate": "c-0002@1", "rationale": "same"}],
    }
    response_path = orchestrator.response_path(round_dir)
    response_path.write_text(json.dumps(response), encoding="utf-8")
    expected_payload = response_path.read_bytes()
    expected_hash = "sha256:" + hashlib.sha256(expected_payload).hexdigest()
    request_hash = (
        "sha256:" + hashlib.sha256(orchestrator.request_path(round_dir).read_bytes()).hexdigest()
    )

    original_create = store.create_owned_bytes

    def fail_applied_create(target, payload):
        if Path(target).name == "RESPONSE.json.applied":
            raise RuntimeError("injected materialization failure")
        return original_create(target, payload)

    monkeypatch.setattr(store, "create_owned_bytes", fail_applied_create)
    with pytest.raises(RuntimeError, match="injected materialization failure"):
        _call_resume_round_one(store, 2)

    checkpoint = json.loads((store.run_dir / "run.json").read_text(encoding="utf-8"))
    assert checkpoint["lifecycle_state"] == "response-applying"
    assert checkpoint["applied_response"] == {
        "version": 1,
        "round": 2,
        "question": "merge",
        "request_sha256": request_hash,
        "sha256": expected_hash,
        "records": 1,
    }
    assert response_path.exists()
    assert not response_path.with_suffix(".json.applying").exists()
    assert not response_path.with_suffix(".json.applied").exists()

    monkeypatch.setattr(store, "create_owned_bytes", original_create)
    _call_resume_round_one(store, 2)
    assert response_path.with_suffix(".json.applied").read_bytes() == expected_payload
    assert not response_path.exists()


def test_response_application_and_digest_use_one_captured_snapshot(tmp_path, monkeypatch):
    store = _store(tmp_path, "run-single-response-snapshot")
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [])
    response = orchestrator.response_path(round_dir)
    original = b'{"version": 1, "merges": []}'
    response.write_bytes(original)
    real_read = store.read_owned_bytes
    response_reads = 0

    def swap_after_read(path, *, max_bytes=32 * 1024 * 1024):
        nonlocal response_reads
        payload = real_read(path, max_bytes=max_bytes)
        if Path(path).name == "RESPONSE.json":
            response_reads += 1
            Path(path).write_bytes(
                b'{"version": 1, "merges": [{"canonical": "x", "duplicate": "y"}]}'
            )
        return payload

    monkeypatch.setattr(store, "read_owned_bytes", swap_after_read)

    with pytest.raises(UsageError, match="changed after validation"):
        _call_resume_round_one(store, 2)

    applied = round_dir / "RESPONSE.json.applied"
    checkpoint = json.loads((store.run_dir / "run.json").read_text())
    assert response_reads == 2
    assert applied.read_bytes() == original
    assert checkpoint["applied_response"]["sha256"] == (
        "sha256:" + hashlib.sha256(original).hexdigest()
    )


def test_response_symlink_is_refused_without_a_state_transition(tmp_path):
    store = _store(tmp_path, "run-response-symlink")
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [])
    outside = tmp_path / "outside-response.json"
    outside.write_text('{"version": 1, "merges": []}', encoding="utf-8")
    response = orchestrator.response_path(round_dir)
    response.symlink_to(outside)

    with pytest.raises(UsageError, match="response artifact must be a regular file"):
        _call_resume_round_one(store, 2)

    assert response.is_symlink()
    assert not (round_dir / "RESPONSE.json.applying").exists()
    assert not (round_dir / "RESPONSE.json.applied").exists()
    assert not (store.run_dir / "run.json").exists()


def test_retry_recovers_matching_applied_response_after_rename(tmp_path):
    store = _store(tmp_path, "run-recover-applied")
    store.ledger.append(_claim(1, "defect A"))
    store.ledger.append(_claim(2, "defect A reworded"))
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [_claim(1), _claim(2)])
    orchestrator.response_path(round_dir).write_text(
        json.dumps({"version": 1, "merges": []}), encoding="utf-8"
    )
    response_path = orchestrator.response_path(round_dir)
    payload = response_path.read_bytes()
    applied_path = response_path.with_suffix(".json.applied")
    response_path.rename(applied_path)
    store.write_run_json(
        {
            "lifecycle_state": "response-applied",
            "applied_response": {
                "version": 1,
                "round": 2,
                "question": "merge",
                "request_sha256": _request_digest(round_dir),
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "records": 0,
            },
        }
    )
    args = _args(mode="report")
    args._resume_meta = json.loads((store.run_dir / "run.json").read_text())

    resumed = resume_round_one(
        args,
        store,
        ReviewState.replay(store.ledger.records()),
        [],
        {},
        None,
        None,
        "",
        None,
        None,
        threading.Event(),
        Budget(max_calls=100, max_wall_clock_s=3600.0, started=0.0),
        2,
        lambda _p: None,
    )

    assert resumed.aliases == []
    assert applied_path.read_bytes() == payload


def test_tampered_applied_response_is_refused_without_mutation(tmp_path):
    store = _store(tmp_path, "run-tampered-applied")
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [])
    applied_path = round_dir / "RESPONSE.json.applied"
    applied_path.write_text('{"version": 1, "merges": []}', encoding="utf-8")
    store.write_run_json(
        {
            "lifecycle_state": "response-applied",
            "applied_response": {
                "version": 1,
                "round": 2,
                "question": "merge",
                "request_sha256": _request_digest(round_dir),
                "sha256": "sha256:" + "0" * 64,
                "records": 0,
            },
        }
    )
    before = {
        "run": (store.run_dir / "run.json").read_bytes(),
        "applied": applied_path.read_bytes(),
        "ledger": (
            (store.run_dir / "claims.jsonl").read_bytes()
            if (store.run_dir / "claims.jsonl").exists()
            else b""
        ),
    }
    args = _args(mode="report")
    args._resume_meta = json.loads(before["run"])

    with pytest.raises(UsageError, match=r"applied response.*hash"):
        resume_round_one(
            args,
            store,
            ReviewState.replay(store.ledger.records()),
            [],
            {},
            None,
            None,
            "",
            None,
            None,
            threading.Event(),
            Budget(max_calls=100, max_wall_clock_s=3600.0, started=0.0),
            2,
            lambda _p: None,
        )

    assert (store.run_dir / "run.json").read_bytes() == before["run"]
    assert applied_path.read_bytes() == before["applied"]
    ledger = store.run_dir / "claims.jsonl"
    assert (ledger.read_bytes() if ledger.exists() else b"") == before["ledger"]


def test_hostile_request_is_refused_without_applying_or_rewriting_response(tmp_path):
    store = _store(tmp_path, "run-hostile-request")
    store.ledger.append(_claim(1))
    round_dir = store.round_dir(2)
    outside = tmp_path / "outside-request.json"
    outside.write_text('{"question": "merge"}', encoding="utf-8")
    orchestrator.request_path(round_dir).symlink_to(outside)
    response = orchestrator.response_path(round_dir)
    response.write_text('{"version": 1, "merges": []}', encoding="utf-8")
    before = response.read_bytes()

    with pytest.raises(UsageError, match=r"orchestrator request.*regular file"):
        _call_resume_round_one(store, 2)

    assert response.read_bytes() == before
    assert not response.with_suffix(".json.applied").exists()
    assert not (store.run_dir / "run.json").exists()


@pytest.mark.parametrize(
    "payload",
    [
        b"{malformed",
        b'{"version": 1, "merges": "not-an-array"}',
        b'{"version": 1, "merges": [{"canonical": "missing", "duplicate": "also-missing"}]}',
    ],
)
def test_invalid_response_is_refused_without_any_state_transition(tmp_path, payload):
    store = _store(tmp_path, "run-invalid-response")
    store.ledger.append(_claim(1))
    round_dir = store.round_dir(2)
    orchestrator.write_request(round_dir, store.run_id, 2, [_claim(1)])
    response = orchestrator.response_path(round_dir)
    response.write_bytes(payload)
    before = response.read_bytes()

    with pytest.raises(UsageError):
        _call_resume_round_one(store, 2)

    assert response.read_bytes() == before
    assert not (round_dir / "RESPONSE.json.applying").exists()
    assert not (round_dir / "RESPONSE.json.applied").exists()
    assert not (store.run_dir / "run.json").exists()


@pytest.mark.parametrize(
    "request_payload",
    [
        {},
        {"version": 1, "run_id": "other", "round": 2, "question": "merge"},
        {"version": 1, "run_id": "run-request-binding", "round": 3, "question": "merge"},
        {"version": 1, "run_id": "run-request-binding", "round": 2, "question": "unknown"},
        {"version": 1, "run_id": "run-request-binding", "round": 2, "question": 1},
    ],
)
def test_response_requires_the_exact_outstanding_request_before_mutation(tmp_path, request_payload):
    store = _store(tmp_path, "run-request-binding")
    store.ledger.append(_claim(1))
    round_dir = store.round_dir(2)
    orchestrator.request_path(round_dir).write_text(json.dumps(request_payload), encoding="utf-8")
    response = orchestrator.response_path(round_dir)
    response.write_text('{"version": 1, "merges": []}', encoding="utf-8")
    before = {
        "ledger": (store.run_dir / "claims.jsonl").read_bytes(),
        "request": orchestrator.request_path(round_dir).read_bytes(),
        "response": response.read_bytes(),
    }

    with pytest.raises(UsageError, match="outstanding orchestrator request"):
        _call_resume_round_one(store, 2)

    assert (store.run_dir / "claims.jsonl").read_bytes() == before["ledger"]
    assert orchestrator.request_path(round_dir).read_bytes() == before["request"]
    assert response.read_bytes() == before["response"]
    assert not list(round_dir.glob("RESPONSE.json.*"))
    assert not (store.run_dir / "run.json").exists()
