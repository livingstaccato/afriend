"""Rendering and lifecycle status checks split from the core status contract."""

import json

import pytest

from afriend.commands import status

from test_status import _args, _event, _run


def test_status_and_watch_use_only_the_latest_lifecycle_invocation(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root, state="waiting-for-orchestrator", events=False)
    first_start = _event(
        "run_started", {"mode": "report", "profile": "quick", "scope": "doc", "status": "started"}
    )
    first_finish = _event("run_finished", {"status": "halted", "next_action": "resume"})
    resumed_start = _event(
        "run_started",
        {"mode": "crossexam", "profile": "balanced", "scope": "repo", "status": "started"},
    )
    resumed_finish = _event(
        "run_finished", {"status": "completed", "next_action": "inspect_report"}
    )
    (run / "events.jsonl").write_text(
        first_start + "\n" + first_finish + "\n" + resumed_start + "\n", encoding="utf-8"
    )
    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["state"], summary["mode"], summary["profile"], summary["scope"]) == (
        "live",
        "crossexam",
        "balanced",
        "repo",
    )
    observed = list(
        status.watch_events(
            run / "events.jsonl",
            root=root,
            poll_s=0,
            start_at_end=True,
            snapshots=[
                first_start + "\n" + first_finish + "\n" + resumed_start + "\n",
                first_start
                + "\n"
                + first_finish
                + "\n"
                + resumed_start
                + "\n"
                + resumed_finish
                + "\n",
            ],
        )
    )
    assert [event.type for event in observed] == ["run_finished"]


def test_status_surfaces_safe_scope_rounds_and_finished_friend_rows(tmp_path, capsys):
    root = tmp_path / "runs"
    run = _run(root)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["rounds_run"] = 2
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
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    (run / "events.jsonl").write_text(
        _event("run_started", {"mode": "report", "profile": "quick", "status": "started"})
        + "\n"
        + _event(
            "friend_finished",
            {
                "friend": "fake-doc-0",
                "provider": "fake",
                "lens": "configured",
                "round": 1,
                "duration_s": 1.0,
                "status": "succeeded",
            },
        )
        + "\n"
        + _event(
            "friend_failed",
            {
                "friend": "fake-repo-0",
                "provider": "fake",
                "lens": "configured",
                "round": 2,
                "duration_s": 2.0,
                "status": "failed",
            },
        )
        + "\n"
        + _event("round_finished", {"round": 2, "status": "completed"})
        + "\n"
        + _event("run_finished", {"status": "completed", "next_action": "inspect_report"})
        + "\n",
        encoding="utf-8",
    )
    assert status.cmd_status(_args("run-status", out=root, json_output=True)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["scope"] == "repo"
    assert summary["rounds"] == {"current": 2, "final": 2}
    assert [row["status"] for row in summary["friends"]["rows"]] == ["succeeded", "failed"]


@pytest.mark.parametrize("state", ["terminal", "running"])
def test_watch_reports_unavailable_events_and_returns(tmp_path, capsys, state):
    root = tmp_path / "runs"
    _run(root, state=state, events=False)
    assert status.cmd_status(_args("run-status", out=root, watch=True)) == 0
    assert "live events unavailable" in capsys.readouterr().err
