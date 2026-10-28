"""Shipped Pi adapter through the real CLI and a strict, offline subprocess.

Only the executable is substituted. Safe PATH excludes real agent CLIs and
OS sandbox launchers; --allow-unsandboxed-friend records that explicit test
downgrade. OS enforcement has its own real-platform tests. This executable
shim uses a POSIX shebang; Windows process behavior is not asserted here.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from e2e_helpers import AF, _env, _git_commit, _git_repo
import pytest

pytestmark = pytest.mark.posix_only(reason="Pi test executable uses a POSIX shebang")


@pytest.fixture
def pi(tmp_path):
    env = _env()
    home = tmp_path / "home"
    home.mkdir()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        PI_TEST_LOG=str(tmp_path / "calls.jsonl"),
    )
    executable = Path(env["PATH"]) / "pi"
    source = Path(__file__).with_name("pi_cli_stub.py").read_text()
    executable.write_text(f"#!{sys.executable}\n" + source)
    executable.chmod(0o700)
    artifact = tmp_path / "spec.md"
    artifact.write_text("# Offline review\nRequests reach the handler without validation.\n")

    class Harness:
        def cli(self, *args, fast_timeout=False):
            entrypoint = [str(AF)]
            if fast_timeout:
                # Generic dispatch tests cover the 60-second grace arithmetic.
                # Shorten only that grace in this child to exercise real CLI
                # timeout persistence/cleanup without a minute-long sleep.
                entrypoint = [
                    "-c",
                    "import sys; import afriend.dispatch as d; "
                    "d.KILL_GRACE_S = 0; from afriend.cli import main; "
                    "sys.exit(main(sys.argv[1:]))",
                ]
            return subprocess.run(
                [sys.executable, *entrypoint, *map(str, args)],
                env=env,
                capture_output=True,
                text=True,
                timeout=80,
                cwd=tmp_path,
            )

        def run(
            self,
            *extra,
            mode="report",
            models=("upheld-a", "upheld-b"),
            policy="distinct-sessions",
            fast_timeout=False,
        ):
            friends = []
            for index, model in enumerate(models):
                friends += ["--friend", f"pi:{'security' if index == 0 else 'ops'}:test/{model}"]
            return self.cli(
                "run",
                self.artifact,
                "--out",
                tmp_path / "runs",
                "--mode",
                mode,
                "--qualification-policy",
                policy,
                "--allow-unsandboxed-friend",
                "--pass-env",
                "PI_TEST_LOG",
                "--no-progress",
                *friends,
                *extra,
                fast_timeout=fast_timeout,
            )

        @property
        def directory(self):
            return next((tmp_path / "runs").glob("run-*"))

        @property
        def meta(self):
            return json.loads((self.directory / "run.json").read_text())

        @property
        def ledger(self):
            if not (self.directory / "claims.jsonl").exists():
                return []
            return [
                json.loads(line)
                for line in (self.directory / "claims.jsonl").read_text().splitlines()
            ]

        @property
        def calls(self):
            return [json.loads(line) for line in Path(env["PI_TEST_LOG"]).read_text().splitlines()]

        def status(self):
            result = self.cli("status", self.directory, "--out", tmp_path / "runs", "--json")
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

    harness = Harness()
    harness.env = env
    harness.artifact = artifact
    return harness


@pytest.mark.parametrize(
    ("mode", "exit_code"), [("report", 0), ("crossexam", 0), ("gate", 1), ("loop", 0)]
)
def test_pi_all_modes_dispatch_and_persist_real_findings(pi, mode, exit_code):
    result = pi.run("--effort", "high", "--max-loop-iterations", "4", mode=mode)
    assert result.returncode == exit_code, result.stderr
    assert {row["claim"] for row in pi.ledger if row["type"] == "claim"} == {
        "Missing guard upheld-a",
        "Missing guard upheld-b",
    }
    assert {row["cli"] for row in pi.meta["roster"]} == {"pi"}
    rows = pi.meta["friends"]
    assert {row["external_tool_policy"] for row in rows} == {"deny"}
    assert {row["external_tools"] for row in rows} == {"denied"}
    assert {row["effort"] for row in rows} == {"high"}
    assert {call["thinking"] for call in pi.calls} == {"high"}
    assert {call["model"] for call in pi.calls} == {"test/upheld-a", "test/upheld-b"}
    assert (pi.directory / "report.md").is_file()
    if mode != "report":
        assert any(call["judging"] for call in pi.calls)
        assert {row["round"] for row in rows} >= {1, 2}
        assert set(pi.meta["claim_states"].values()) == {"settled-upheld"}
        assert {row["judge"] for row in pi.ledger if row["type"] == "verdict"} == {
            "pi/security@test/upheld-a+high",
            "pi/ops@test/upheld-b+high",
        }
    if mode == "gate":
        assert pi.meta["gate_decision"] == "blocked"
    if mode == "loop":
        assert pi.meta["dry_streak"] == 2
        assert pi.meta["iterations_run"] == 3
        assert any(row["type"] == "alias" for row in pi.ledger)


def test_pi_waits_for_transient_error_recovery(pi):
    result = pi.run(models=("retry-a", "retry-b"))
    assert result.returncode == 0, result.stderr
    assert len([row for row in pi.ledger if row["type"] == "claim"]) == 2


@pytest.mark.git
def test_pi_repo_scope_uses_and_removes_git_worktrees(pi):
    repo = _git_repo(pi.artifact.parent / "repo")
    pi.artifact = repo / "spec.md"
    pi.artifact.write_text("# Contract\nNo validation guard exists.\n")
    subprocess.run(["git", "add", "spec.md"], cwd=repo, env=pi.env, check=True, capture_output=True)
    _git_commit(repo, "base")
    result = pi.run()
    assert result.returncode == 0, result.stderr
    assert {row["scope"] for row in pi.meta["roster"]} == {"repo"}
    assert all(Path(call["cwd"]) != repo and not Path(call["cwd"]).exists() for call in pi.calls)
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        env=pi.env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert worktrees.stdout.count("worktree ") == 1
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        env=pi.env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_pi_large_artifact_reaches_stdin_without_truncation(pi):
    pi.artifact.write_text(
        "# Contract\n" + "A long requirement.\n" * 15_000 + "END_LARGE_ARTIFACT\n"
    )
    result = pi.run(models=("large-a",))
    assert result.returncode == 0, result.stderr
    assert len([row for row in pi.ledger if row["type"] == "claim"]) == 1


@pytest.mark.parametrize(
    "models", [("clean-a", "clean-b"), ("refuted-a", "refuted-b", "refuted-c")]
)
def test_pi_gate_clears_clean_or_refuted_findings(pi, models):
    result = pi.run(mode="gate", models=models)
    assert result.returncode == 0, result.stderr
    assert pi.meta["gate_decision"] == "clear"
    assert pi.meta["gate_blocking_claims"] == []


def test_pi_models_preserve_provider_identity(pi):
    result = pi.cli("providers", "models", "pi", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["providers"]["pi"]["models"] == [
        "test/upheld-a",
        "other/upheld-a",
    ]


def test_pi_unauthenticated_inventory_is_unavailable(pi):
    (Path(pi.env["HOME"]) / "empty-catalog").touch()
    result = pi.cli("providers", "models", "pi", "--json")
    answer = json.loads(result.stdout)["providers"]["pi"]
    assert answer["models"] == []
    assert answer["error"] is not None


def test_pi_new_findings_reach_the_loop_iteration_ceiling(pi):
    result = pi.run("--max-loop-iterations", "2", mode="loop", models=("new-a", "new-b"))
    assert result.returncode == 11, result.stderr
    assert pi.meta["iterations_run"] == 2
    assert pi.meta["stop_reason"] == "max-loop-iterations"
    assert pi.meta["dry_streak"] == 0


@pytest.mark.parametrize("scenario", ["auth", "aborted"])
def test_pi_failure_is_visible_in_status_without_claims(pi, scenario):
    result = pi.run(models=(f"{scenario}-a", f"{scenario}-b"))
    assert result.returncode == 1, result.stderr
    assert not any(row["type"] == "claim" for row in pi.ledger)
    summary = pi.status()
    assert summary["friends"]["failed"] == 2
    if scenario == "auth":
        assert "authenticate pi" in result.stderr


def test_pi_halted_review_resumes_with_frozen_roster_and_no_duplicate_claims(pi):
    halted = pi.run("--merge", "orchestrator", "--effort", "low", mode="crossexam")
    assert halted.returncode == 10, halted.stderr
    roster = pi.meta["roster"]
    original_claims = [row for row in pi.ledger if row["type"] == "claim"]
    status = pi.status()
    assert status["state"] == "terminal"
    assert status["outcome"] == "halted"
    assert status["next_action"] == "resume"
    request = pi.directory / "round-1" / "REQUEST.json"
    response = json.loads(request.read_text())
    response["merges"] = []
    request.with_name("RESPONSE.json").write_text(json.dumps(response))
    # Defaults changed after the halt must not replace the saved models.
    assert pi.cli("providers", "set-model", "pi", "test/clean-other").returncode == 0
    resume_args = (
        "run",
        "--resume",
        pi.directory,
        "--out",
        pi.directory.parent,
        "--allow-unsandboxed-friend",
        "--no-progress",
    )
    refused = pi.cli(*resume_args)
    assert refused.returncode == 2
    assert "--pass-env authority must be repeated" in refused.stderr
    assert [row for row in pi.ledger if row["type"] == "claim"] == original_claims
    resumed = pi.cli(*resume_args, "--pass-env", "PI_TEST_LOG")
    assert resumed.returncode == 0, resumed.stderr
    assert pi.meta["roster"] == roster
    assert [row for row in pi.ledger if row["type"] == "claim"] == original_claims
    assert {row["external_tool_policy"] for row in pi.meta["friends"]} == {"deny"}
    assert {call["model"] for call in pi.calls} == {"test/upheld-a", "test/upheld-b"}
    assert {call["thinking"] for call in pi.calls} == {"low"}
    assert any(call["judging"] for call in pi.calls)
    final = pi.status()
    assert final["state"] == "terminal"
    assert final["friends"]["failed"] == 0


def test_pi_discovery_doctor_and_provider_settings(pi):
    doctor = pi.cli("doctor", "--json")
    assert doctor.returncode == 0, doctor.stderr
    row = next(row for row in json.loads(doctor.stdout)["friends"] if row["name"] == "pi")
    assert row["state"] == "ready"
    preview = pi.cli("init", "--guided", "--json")
    assert preview.returncode == 0, preview.stderr
    assert not Path(pi.env["XDG_CONFIG_HOME"]).exists()
    assert pi.cli("providers", "set-model", "pi", "test/upheld-a").returncode == 0
    listed = json.loads(pi.cli("providers", "list", "--json").stdout)
    assert listed["providers"]["pi"] == {"enabled": True, "model": "test/upheld-a"}
    # No explicit friends: only the executable on our safe PATH is discovered.
    result = pi.run(models=())
    assert result.returncode == 0, result.stderr
    assert {row["cli"] for row in pi.meta["roster"]} == {"pi"}
    assert {row["model"] for row in pi.meta["roster"]} == {"test/upheld-a"}
    assert {row["model_source"] for row in pi.meta["roster"]} == {"provider-setting"}
    assert pi.cli("providers", "disable", "pi").returncode == 0
    assert pi.cli("doctor", "--json").returncode == 3
    assert pi.cli("providers", "enable", "pi").returncode == 0
    assert pi.cli("doctor", "--json").returncode == 0


@pytest.mark.parametrize(
    ("extra", "model", "source"),
    [
        ([], "test/upheld-a", "explicit-friend"),
        (["--model", "test/clean-override"], "test/clean-override", "invocation"),
    ],
)
def test_pi_explicit_model_precedence_and_preset(pi, extra, model, source):
    assert pi.cli("providers", "set-model", "pi", "test/clean-provider").returncode == 0
    result = pi.run("--preset", "cheap", *extra)
    assert result.returncode == 0, result.stderr
    assert pi.meta["roster"][0]["model"] == model
    assert pi.meta["roster"][0]["model_source"] == source
    assert {call["thinking"] for call in pi.calls} == {"low"}


@pytest.mark.parametrize(
    ("flags", "independent", "host_self_review"),
    [
        (["--include-self"], False, True),
        (["--fresh-host-worker"], True, False),
    ],
)
def test_pi_explicit_host_roles_reach_saved_roster(pi, flags, independent, host_self_review):
    result = pi.run("--host-provider", "pi", *flags)
    assert result.returncode == 0, result.stderr
    assert {row["independent"] for row in pi.meta["roster"]} == {independent}
    assert {row["host_self_review"] for row in pi.meta["roster"]} == {host_self_review}


def test_pi_host_family_is_excluded_by_default(pi):
    result = pi.run("--host-provider", "pi")
    assert result.returncode != 0
    assert not Path(pi.env["PI_TEST_LOG"]).exists()


def test_pi_lenses_and_models_do_not_satisfy_cross_provider_policy(pi):
    result = pi.run(mode="gate", policy="cross-provider")
    assert result.returncode != 0
    assert not Path(pi.env["PI_TEST_LOG"]).exists()


@pytest.mark.process
def test_pi_timeout_kills_child_and_records_failure(pi):
    result = pi.run("--timeout", "1", models=("hang-a",), fast_timeout=True)
    assert result.returncode == 1, result.stderr
    assert pi.meta["friends"][0]["status"].startswith("failed: timeout")
    with pytest.raises(ProcessLookupError):
        os.kill(pi.calls[0]["pid"], 0)
    summary = pi.status()
    assert summary["friends"]["failed"] == 1


@pytest.mark.process
def test_pi_cancel_kills_child_and_saves_status(pi):
    command = [
        sys.executable,
        str(AF),
        "run",
        str(pi.artifact),
        "--out",
        str(pi.artifact.parent / "runs"),
        "--friend",
        "pi:security:test/hang-a",
        "--allow-unsandboxed-friend",
        "--pass-env",
        "PI_TEST_LOG",
        "--no-progress",
    ]
    process = subprocess.Popen(
        command,
        env=pi.env,
        cwd=pi.artifact.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not Path(pi.env["PI_TEST_LOG"]).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert Path(pi.env["PI_TEST_LOG"]).exists(), "Pi child did not start"
        process.send_signal(signal.SIGTERM)
        _stdout, stderr = process.communicate(timeout=10)
        assert process.returncode != 0, stderr
        with pytest.raises(ProcessLookupError):
            os.kill(pi.calls[0]["pid"], 0)
        summary = pi.status()
        assert summary["state"] == "terminal"
        assert summary["outcome"] == "incomplete"
        assert process.returncode == 128 + signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
