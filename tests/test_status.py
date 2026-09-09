"""Read-only inspection of persisted afriend runs."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from e2e_helpers import _git_commit, _git_repo
import pytest

from afriend import cli
from afriend.commands import run as run_module, status
from afriend.errors import UsageError
from afriend.events import MAX_EVENT_LOG_BYTES, EventRecord, EventWriter
from afriend.progress import Progress


def _args(run_id: str, *, out: Path | None = None, json_output: bool = False, watch: bool = False):
    return argparse.Namespace(
        run_id=run_id, out=str(out) if out is not None else None, json=json_output, watch=watch
    )


def _event(event_type: str, payload: dict[str, object]) -> str:
    return json.dumps(
        EventRecord.create(
            event_type, payload, run_id="run-status", timestamp="2026-09-03T12:00:00Z"
        ).to_dict()
    )


def _run(root: Path, *, state: str = "terminal", events: bool = True) -> Path:
    run = root / "run-status"
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": state,
                "mode": "report",
                "profile": "quick",
                "downgrades": ["doc scope only"],
                "friends": [{"name": "fake-security-0", "status": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    (run / "claims.jsonl").write_text(
        json.dumps(
            {
                "type": "claim",
                "id": "c-0001@1",
                "supersedes": None,
                "origin": ["fake-security-0"],
                "lens": "security",
                "round": 1,
                "advisory": False,
                "severity": "high",
                "claim": "Missing check",
                "location": "src/app.py:1",
                "evidence": "missing check",
                "failure_scenario": "bad input",
                "suggested_fix": "add check",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if events:
        (run / "events.jsonl").write_text(
            _event("run_started", {"mode": "report", "profile": "quick", "status": "started"})
            + "\n"
            + _event("run_finished", {"status": "completed", "next_action": "inspect_report"})
            + "\n",
            encoding="utf-8",
        )
    return run


def test_status_summarizes_a_terminal_run_without_mutating(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root)
    before = {
        path: path.stat().st_mode for path in [root, run, run / "run.json", run / "claims.jsonl"]
    }

    assert status.cmd_status(_args("run-status", out=root)) == 0

    output = capsys.readouterr().out
    assert "terminal" in output
    assert "completed" in output
    assert "next: inspect_report" in output
    assert {path: path.stat().st_mode for path in before} == before
    assert not (run / ".lock").exists()


def test_status_json_is_versioned_and_uses_run_artifacts_when_events_are_absent(tmp_path, capsys):
    root = tmp_path / "runs"
    _run(root, events=False)

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 4
    assert payload["state"] == "terminal"
    assert payload["mode"] == "report"
    assert payload["profile"] == "quick"
    assert payload["claims"] == {"by_status": {"pending": 1}, "total": 1}
    assert payload["downgrades"] == ["doc scope only"]


def test_status_triage_projects_an_unresolved_final_claim_without_transcript_text(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    secret = "secret raw completion must not appear"
    (run / "round-1").mkdir()
    (run / "round-1" / "fake-security-0.raw").write_text(secret, encoding="utf-8")
    (run / "round-1" / "fake-security-0.prompt").write_text(secret, encoding="utf-8")
    (run / "round-1" / "fake-security-0.err").write_text(secret, encoding="utf-8")
    (run / "round-1" / "fake-security-0.json").write_text("{}", encoding="utf-8")
    (run / "report.md").write_text(secret, encoding="utf-8")
    claim = json.loads((run / "claims.jsonl").read_text(encoding="utf-8"))
    claim["claim"] = secret
    claim["evidence"] = secret
    (run / "claims.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["roster"] = [
        {
            "name": "fake-security-0",
            "cli": "fake",
            "lens": "security",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 1,
        }
    ]
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    loaded: list[Path] = []
    checked: list[Path] = []
    original_read = status.secure_read_bytes
    original_regular_exists = status.secure_regular_exists

    def record_read(path, **kwargs):
        loaded.append(Path(path))
        return original_read(path, **kwargs)

    def record_regular_exists(path, **kwargs):
        checked.append(Path(path))
        return original_regular_exists(path, **kwargs)

    monkeypatch.setattr(status, "secure_read_bytes", record_read)
    monkeypatch.setattr(status, "secure_regular_exists", record_regular_exists)

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["triage"] == {
        "evidence_paths": [str(run / "round-1" / "fake-security-0.json")],
        "final_claim_ids": ["c-0001@1"],
        "final_findings": [
            {
                "evidence_paths": [str(run / "round-1" / "fake-security-0.json")],
                "id": "c-0001@1",
                "severity": "high",
                "status": "unresolved",
            }
        ],
        "ledger_path": str(run / "claims.jsonl"),
        "report_path": str(run / "report.md"),
        "unresolved_claim_ids": ["c-0001@1"],
        "unresolved_count": 1,
    }
    assert secret not in json.dumps(summary)
    assert all(path.suffix not in {".raw", ".prompt", ".err"} for path in loaded)
    assert all(path.suffix not in {".raw", ".prompt", ".err"} for path in checked)


def test_status_triage_uses_final_resolved_claims_and_renders_them(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    predecessor = json.loads((run / "claims.jsonl").read_text(encoding="utf-8"))
    successor = {**predecessor, "id": "c-0001@2", "supersedes": "c-0001@1"}
    with (run / "claims.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(successor) + "\n")
        handle.write(
            json.dumps(
                {
                    "type": "resolution",
                    "claim_id": "c-0001@2",
                    "disposition": "fixed",
                    "author": "operator",
                    "evidence": "src/app.py:1",
                    "round": 2,
                    "verified": "location-changed",
                }
            )
            + "\n"
        )

    assert status.cmd_status(_args("run-status", out=root)) == 0

    output = capsys.readouterr().out
    assert "final findings: c-0001@2 [high, fixed]" in output
    assert "final findings: c-0001@1" not in output
    assert "unresolved=0" in output


def test_status_triage_includes_each_aliased_claims_original_parsed_evidence(tmp_path):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    original = json.loads((run / "claims.jsonl").read_text(encoding="utf-8"))
    duplicate = {
        **original,
        "id": "c-0002@1",
        "origin": ["fake-ops-0"],
        "lens": "ops",
        "round": 2,
    }
    with (run / "claims.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(duplicate) + "\n")
        handle.write(
            json.dumps(
                {
                    "type": "alias",
                    "canonical": "c-0001@1",
                    "duplicate": "c-0002@1",
                    "round": 2,
                    "source": "exact",
                    "rationale": "same finding",
                }
            )
            + "\n"
        )
    (run / "round-1").mkdir()
    (run / "round-1" / "fake-security-0.json").write_text("{}", encoding="utf-8")
    (run / "round-2").mkdir()
    (run / "round-2" / "fake-ops-0.json").write_text("{}", encoding="utf-8")
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["roster"] = [
        {
            "name": "fake-security-0",
            "cli": "fake",
            "lens": "security",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 1,
        },
        {
            "name": "fake-ops-0",
            "cli": "fake",
            "lens": "ops",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 1,
        },
    ]
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    summary = status.summarize(run, root=root)

    assert summary["triage"]["final_claim_ids"] == ["c-0001@1"]
    assert summary["triage"]["final_findings"][0]["evidence_paths"] == [
        str(run / "round-1" / "fake-security-0.json"),
        str(run / "round-2" / "fake-ops-0.json"),
    ]


def test_status_triage_keeps_predecessor_evidence_at_its_original_round(tmp_path):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    predecessor = json.loads((run / "claims.jsonl").read_text(encoding="utf-8"))
    successor = {
        **predecessor,
        "id": "c-0001@2",
        "origin": ["fake-ops-0"],
        "lens": "ops",
        "round": 2,
        "supersedes": "c-0001@1",
    }
    with (run / "claims.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(successor) + "\n")
    (run / "round-1").mkdir()
    (run / "round-1" / "fake-security-0.json").write_text("{}", encoding="utf-8")
    (run / "round-2").mkdir()
    (run / "round-2" / "fake-ops-0.json").write_text("{}", encoding="utf-8")
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["roster"] = [
        {
            "name": "fake-security-0",
            "cli": "fake",
            "lens": "security",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 1,
        },
        {
            "name": "fake-ops-0",
            "cli": "fake",
            "lens": "ops",
            "model": None,
            "effort": None,
            "scope": "doc",
            "timeout": 1,
        },
    ]
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    summary = status.summarize(run, root=root)

    assert summary["triage"]["final_claim_ids"] == ["c-0001@2"]
    assert summary["triage"]["final_findings"][0]["evidence_paths"] == [
        str(run / "round-1" / "fake-security-0.json"),
        str(run / "round-2" / "fake-ops-0.json"),
    ]


def test_status_triage_uses_validated_claim_states_with_resolution_precedence(tmp_path):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["claim_states"] = {"c-0001@1": "settled-refuted"}
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    refuted = status.summarize(run, root=root)["triage"]

    assert refuted["final_findings"][0]["status"] == "settled-refuted"
    assert refuted["unresolved_claim_ids"] == []
    assert refuted["unresolved_count"] == 0

    with (run / "claims.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "resolution",
                    "claim_id": "c-0001@1",
                    "disposition": "fixed",
                    "author": "operator",
                    "evidence": "src/app.py:1",
                    "round": 2,
                    "verified": "location-changed",
                }
            )
            + "\n"
        )

    resolved = status.summarize(run, root=root)["triage"]

    assert resolved["final_findings"][0]["status"] == "fixed"
    assert resolved["unresolved_count"] == 0


def test_status_triage_keeps_empty_and_event_only_runs_unknown_or_absent(tmp_path, capsys):
    root = tmp_path / "runs"
    eventless = _run(root, events=False)
    (eventless / "claims.jsonl").unlink()
    event_only = root / "event-only"
    event_only.mkdir()
    (event_only / "events.jsonl").write_text(
        _event("run_started", {"mode": "report", "profile": "quick", "status": "started"}) + "\n",
        encoding="utf-8",
    )

    eventless_summary = status.summarize(eventless, root=root)
    event_summary = status.summarize(event_only, root=root)

    expected = {
        "evidence_paths": [],
        "final_claim_ids": [],
        "final_findings": [],
        "ledger_path": None,
        "report_path": None,
        "unresolved_claim_ids": [],
        "unresolved_count": 0,
    }
    assert eventless_summary["triage"] == expected
    assert event_summary["triage"] == expected


def test_status_projects_persisted_zero_response_completeness_safely(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["friends"] = [
        {
            "name": "codex-security",
            "independent": True,
            "round": 1,
            "status": "failed: DNS temporary failure",
        }
    ]
    meta["review_completeness"] = {
        "state": "incomplete",
        "answered": 0,
        "dispatched": 1,
        "reasons": ["codex-security: DNS temporary failure"],
        "message": "review incomplete: 0/1 friends answered; codex-security: DNS temporary failure",
    }
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["review_completeness"] == meta["review_completeness"]
    assert "DNS temporary failure" in status._render(summary)


@pytest.mark.parametrize("saved_friends", [None, 7], ids=("null", "scalar"))
def test_status_ignores_nonlist_persisted_friends_for_completeness(tmp_path, capsys, saved_friends):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["friends"] = saved_friends
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    assert json.loads(capsys.readouterr().out)["review_completeness"] is None


def test_status_projects_safe_friend_metadata_without_events(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["roster"] = [
        {
            "name": "fake-doc-0",
            "cli": "fake",
            "lens": "security",
            "scope": "doc",
            "model": None,
            "effort": None,
            "timeout": 1,
        },
        {
            "name": "fake-repo-0",
            "cli": "fake",
            "lens": "ops",
            "scope": "repo",
            "model": None,
            "effort": None,
            "timeout": 1,
        },
    ]
    meta["friends"] = [
        {"name": "fake-doc-0", "round": 1, "status": "ok"},
        {"name": "fake-repo-0", "round": 2, "status": "failed: timed out"},
    ]
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["friends"]["rows"] == [
        {
            "name": "fake-doc-0",
            "provider": "fake",
            "scope": "doc",
            "round": 1,
            "status": "succeeded",
        },
        {
            "name": "fake-repo-0",
            "provider": "fake",
            "scope": "repo",
            "round": 2,
            "status": "failed",
        },
    ]
    assert summary["friends"]["finished"] == 2
    assert summary["friends"]["failed"] == 1


def test_status_rejects_an_empty_directory(tmp_path):
    root = tmp_path / "runs"
    (root / "run-status").mkdir(parents=True)

    with pytest.raises(UsageError, match="not a run directory"):
        status.cmd_status(_args("run-status", out=root))


@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_status_wraps_unreadable_event_artifacts_as_usage_errors(tmp_path, kind):
    root = tmp_path / "runs"
    run = _run(root, events=False)
    events_path = run / "events.jsonl"
    if kind == "directory":
        events_path.mkdir()
    else:
        events_path.write_bytes(b"x" * (MAX_EVENT_LOG_BYTES + 1))

    with pytest.raises(UsageError, match="cannot read lifecycle events"):
        status.cmd_status(_args("run-status", out=root))


def test_status_rejects_path_outside_the_selected_run_root(tmp_path):
    root = tmp_path / "runs"
    outside = _run(tmp_path / "elsewhere")
    root.mkdir()

    with pytest.raises(UsageError, match="outside the run root"):
        status.cmd_status(_args(str(outside), out=root))


def test_status_accepts_an_explicit_directory_only_when_contained(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root)

    assert status.cmd_status(_args(str(run), out=root)) == 0

    assert "run-status: terminal" in capsys.readouterr().out


def test_watch_ignores_a_torn_tail_then_stops_at_run_finished(tmp_path):
    root = tmp_path / "runs"
    run = _run(root, state="running", events=False)
    events_path = run / "events.jsonl"
    started = _event("run_started", {"mode": "report", "profile": "quick", "status": "started"})
    finished = _event("run_finished", {"status": "completed", "next_action": "inspect_report"})
    events_path.write_text(started + "\n" + finished[:20], encoding="utf-8")

    observed = list(
        status.watch_events(
            events_path,
            root=root,
            poll_s=0,
            snapshots=[started + "\n" + finished[:20], started + "\n" + finished + "\n"],
        )
    )

    assert [event.type for event in observed] == ["run_started", "run_finished"]


def test_watch_started_at_end_does_not_repeat_prior_progress(tmp_path):
    root = tmp_path / "runs"
    run = _run(root, state="running", events=False)
    started = _event("run_started", {"mode": "report", "profile": "quick", "status": "started"})
    finished = _event("run_finished", {"status": "completed", "next_action": "inspect_report"})

    observed = list(
        status.watch_events(
            run / "events.jsonl",
            root=root,
            poll_s=0,
            start_at_end=True,
            snapshots=[started + "\n", started + "\n" + finished + "\n"],
        )
    )

    assert [event.type for event in observed] == ["run_finished"]


def test_status_summarizes_a_live_event_first_run_before_run_json_exists(tmp_path, capsys):
    """cmd_run writes this durable event before its first run.json checkpoint."""
    root = tmp_path / "runs"
    run = root / "run-status"
    run.mkdir(parents=True)
    writer = EventWriter(run / "events.jsonl", root, "run-status")
    writer.append(
        EventRecord.create(
            "run_started",
            {"mode": "crossexam", "profile": "balanced", "status": "started"},
            run_id="run-status",
        )
    )

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["state"] == "live"
    assert summary["mode"] == "crossexam"
    assert summary["profile"] == "balanced"
    assert summary["rounds"] == {"current": 0, "final": None}


def test_cmd_run_exposes_an_event_first_status_checkpoint(monkeypatch, tmp_path, capsys):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")
    root = tmp_path / "runs"
    fake = Path(__file__).with_name("fake_friend.py")
    monkeypatch.setenv("AF_FAKE_FRIEND", f"{sys.executable} {fake}")
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    observed: list[dict[str, object]] = []
    original = Progress.run_started

    def inspect_before_metadata(self, mode: str, profile: str, scope: str, **kwargs) -> None:
        original(self, mode, profile, scope, **kwargs)
        run = next(root.iterdir())
        assert not (run / "run.json").exists()
        observed.append(status.summarize(run, root=root))

    monkeypatch.setattr(Progress, "run_started", inspect_before_metadata)

    assert (
        cli.main(
            [
                "run",
                str(artifact),
                "--out",
                str(root),
                "--friend",
                "fake:good",
                "--no-progress",
            ]
        )
        == 0
    )

    assert observed[0]["state"] == "live"
    assert observed[0]["mode"] == "report"
    assert observed[0]["profile"] == "quick"
    assert observed[0]["rounds"] == {
        "current": 0,
        "final": None,
    }
    capsys.readouterr()


def test_cmd_run_refuses_before_dispatch_when_initial_event_cannot_be_persisted(
    monkeypatch, tmp_path, capsys
):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")
    root = tmp_path / "runs"
    fake = Path(__file__).with_name("fake_friend.py")
    monkeypatch.setenv("AF_FAKE_FRIEND", f"{sys.executable} {fake}")
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")

    def fail_initial_event(self, event):
        assert event.type == "run_started"
        raise OSError("disk unavailable")

    dispatched = False

    def must_not_dispatch(*args, **kwargs):
        nonlocal dispatched
        dispatched = True
        raise AssertionError("dispatch reached")

    monkeypatch.setattr(EventWriter, "append", fail_initial_event)
    monkeypatch.setattr(run_module, "run_critique", must_not_dispatch)

    assert (
        cli.main(
            [
                "run",
                str(artifact),
                "--out",
                str(root),
                "--friend",
                "fake:good",
                "--no-progress",
            ]
        )
        == 2
    )
    assert not dispatched
    assert not list(root.iterdir())
    assert "initial lifecycle event" in capsys.readouterr().err


def test_event_first_status_reports_validated_repo_scope(monkeypatch, tmp_path, capsys):
    repo = _git_repo(tmp_path / "repo")
    artifact = repo / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")
    subprocess.run(["git", "add", "spec.md"], cwd=repo, check=True, capture_output=True)
    _git_commit(repo, "add spec")
    root = tmp_path / "runs"
    fake = Path(__file__).with_name("fake_friend.py")
    monkeypatch.setenv("AF_FAKE_FRIEND", f"{sys.executable} {fake}")
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    observed: list[dict[str, object]] = []
    original = Progress.run_started

    def inspect_before_metadata(self, mode: str, profile: str, scope: str, **kwargs) -> None:
        original(self, mode, profile, scope, **kwargs)
        run = next(root.iterdir())
        assert not (run / "run.json").exists()
        observed.append(status.summarize(run, root=root))

    monkeypatch.setattr(Progress, "run_started", inspect_before_metadata)

    assert (
        cli.main(
            [
                "run",
                str(artifact),
                "--out",
                str(root),
                "--friend",
                "fake:good:repo",
                "--no-progress",
            ]
        )
        == 0
    )

    assert observed[0]["scope"] == "repo"
    capsys.readouterr()


def test_repo_started_run_keeps_its_scope_after_a_friend_event(tmp_path, capsys):
    root = tmp_path / "runs"
    run = root / "run-status"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        _event(
            "run_started",
            {"mode": "report", "profile": "quick", "scope": "repo", "status": "started"},
        )
        + "\n"
        + _event(
            "friend_finished",
            {
                "friend": "fake-repo-0",
                "provider": "fake",
                "lens": "configured",
                "round": 1,
                "duration_s": 1.0,
                "status": "succeeded",
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["scope"] == "repo"
    assert summary["friends"]["rows"][0]["scope"] == "unknown"
