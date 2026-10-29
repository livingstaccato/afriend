"""Release identity must be bound to actual complete successful quality evidence."""

import copy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_ci_gate", Path(__file__).resolve().parents[1] / "ci/verify_release_ci.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40


def run_record(**overrides):
    record = dict(
        id=17,
        workflow_id=42,
        head_sha=SHA,
        head_branch="main",
        event="push",
        status="completed",
        conclusion="success",
    )
    return dict(record, **overrides)


def jobs():
    result = []
    names = [
        "quality (3.11)",
        "quality (3.12)",
        "quality (3.13)",
        "windows",
        "Windows startup (claude)",
        "Windows startup (codex)",
        "Windows startup (opencode)",
        "Windows startup (pi)",
    ]
    for index, name in enumerate(names):
        if name.startswith("quality"):
            steps = ["pytest", "assert containment tests ran"]
            if name == "quality (3.13)":
                steps.append("mutation-probe")
        elif name == "windows":
            steps = ["pytest"]
        else:
            steps = ["Install real reviewer CLI", "Exercise native startup and expected rejection"]
        result.append(
            dict(
                id=100 + index,
                run_id=17,
                run_attempt=1,
                head_sha=SHA,
                name=name,
                status="completed",
                conclusion="success",
                steps=[dict(name=step, status="completed", conclusion="success") for step in steps],
            )
        )
    return result


def test_accepts_only_successful_exact_commit_push_main_run():
    assert MODULE.select_successful_run([run_record()], SHA, 42)["id"] == 17
    MODULE.require_successful_jobs(jobs(), SHA, 17)


@pytest.mark.parametrize(
    "override",
    [
        {"head_sha": "b" * 40},
        {"workflow_id": 99},
        {"head_branch": "pi-friend"},
        {"event": "pull_request"},
        {"status": "in_progress", "conclusion": None},
        {"conclusion": "failure"},
        {"conclusion": "cancelled"},
    ],
)
def test_missing_pending_failed_or_unrelated_ci_cannot_release(override):
    with pytest.raises(RuntimeError):
        MODULE.select_successful_run([run_record(**override)], SHA, 42)


def test_older_success_cannot_hide_newer_failed_attempt():
    with pytest.raises(RuntimeError):
        MODULE.select_successful_run(
            [run_record(), run_record(id=18, conclusion="failure")], SHA, 42
        )


def test_no_run_cannot_release():
    with pytest.raises(RuntimeError):
        MODULE.select_successful_run([], SHA, 42)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-job",
        "failed-job",
        "skipped-job",
        "wrong-sha",
        "wrong-run",
        "missing-step",
        "skipped-step",
        "failed-mutation",
        "duplicate-step",
        "duplicate-job",
    ],
)
def test_incomplete_or_false_green_jobs_cannot_release(mutation):
    records = jobs()
    if mutation == "missing-job":
        records.pop()
    elif mutation == "failed-job":
        records[0]["conclusion"] = "failure"
    elif mutation == "skipped-job":
        records[0]["conclusion"] = "skipped"
    elif mutation == "wrong-sha":
        records[0]["head_sha"] = "b" * 40
    elif mutation == "wrong-run":
        records[0]["run_id"] = 1234
    elif mutation == "missing-step":
        records[0]["steps"].pop()
    elif mutation == "skipped-step":
        records[0]["steps"][0]["conclusion"] = "skipped"
    elif mutation == "failed-mutation":
        records[2]["steps"][-1]["conclusion"] = "failure"
    elif mutation == "duplicate-step":
        records[0]["steps"].append(copy.deepcopy(records[0]["steps"][0]))
    elif mutation == "duplicate-job":
        records.append(copy.deepcopy(records[0]))
    with pytest.raises(RuntimeError):
        MODULE.require_successful_jobs(records, SHA, 17)


def test_successful_jobs_from_prior_attempt_survive_partial_ci_rerun():
    records = jobs()
    old = copy.deepcopy(records[2])
    old["conclusion"] = "failure"
    records[2]["run_attempt"] = 2
    records[2]["id"] = 200
    MODULE.require_successful_jobs([old, *records], SHA, 17)


def test_newer_failed_job_cannot_hide_behind_old_success():
    records = jobs()
    new = copy.deepcopy(records[2])
    new.update(run_attempt=2, id=200, conclusion="failure")
    with pytest.raises(RuntimeError):
        MODULE.require_successful_jobs([*records, new], SHA, 17)


def test_verify_binds_api_requests_to_workflow_commit_and_all_attempts(monkeypatch):
    client = MODULE.GitHub("fixture-token")
    calls = []

    def get(path):
        calls.append(path)
        if path.endswith("workflows/ci.yml"):
            return dict(path=".github/workflows/ci.yml", state="active", id=42)
        if "/workflows/42/runs?" in path:
            return {"workflow_runs": [run_record()]}
        if "/runs/17/jobs?" in path:
            return {"jobs": jobs()}
        pytest.fail(f"unexpected API path: {path}")

    monkeypatch.setattr(client, "get", get)
    assert MODULE.verify("owner/repo", SHA, client)["id"] == 17
    assert f"head_sha={SHA}&event=push&branch=main" in calls[1]
    assert "filter=all" in calls[2]


def test_collection_follows_pages_and_rejects_malformed_response(monkeypatch):
    client = MODULE.GitHub("fixture-token")
    calls = []

    def get(path):
        calls.append(path)
        return {"jobs": [{}] * (100 if path.endswith("&page=1") else 1)}

    monkeypatch.setattr(client, "get", get)
    assert len(client.collection("jobs", "jobs")) == 101
    assert len(calls) == 2
    monkeypatch.setattr(client, "get", lambda path: {"jobs": None})
    with pytest.raises(RuntimeError, match="lacks jobs"):
        client.collection("jobs", "jobs")


@pytest.mark.parametrize("payload", [b"not-json", b"[]", b"null"])
def test_api_transport_rejects_invalid_json_or_non_objects(monkeypatch, payload):
    import io

    monkeypatch.setattr(MODULE, "urlopen", lambda request, timeout: io.BytesIO(payload))
    with pytest.raises(RuntimeError):
        MODULE.GitHub("fixture-token").get("repos/owner/repo/actions")


def test_api_transport_fails_closed_on_network_error(monkeypatch):
    def unavailable(request, timeout):
        raise MODULE.URLError("fixture unavailable")

    monkeypatch.setattr(MODULE, "urlopen", unavailable)
    with pytest.raises(RuntimeError, match="cannot verify"):
        MODULE.GitHub("fixture-token").get("repos/owner/repo/actions")


def test_cli_missing_token_never_attempts_network(monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(MODULE, "verify", lambda *args: pytest.fail("unexpected network"))
    assert MODULE.main(["--repository", "owner/repo", "--sha", SHA]) == 1
    assert "actions:read" in capsys.readouterr().err
