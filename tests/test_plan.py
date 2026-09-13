"""Durable, non-mutating proposals built from terminal run triage."""

import json
from pathlib import Path

from afriend import cli
from afriend.commands import status
from afriend.events import EventRecord


def _claim(claim_id: str, *, severity: str = "medium") -> dict[str, object]:
    return {
        "type": "claim",
        "id": claim_id,
        "supersedes": None,
        "origin": ["fake-security-0"],
        "lens": "security",
        "round": 1,
        "advisory": False,
        "severity": severity,
        "claim": f"Finding {claim_id}",
        "location": "src/app.py:1",
        "evidence": f"Evidence for {claim_id}",
        "failure_scenario": "bad input",
        "suggested_fix": "add check",
    }


def _terminal_run(
    tmp_path: Path, *, claims: list[dict[str, object]] | None = None, state: str = "terminal"
) -> tuple[Path, Path]:
    root = tmp_path / "runs"
    run = root / "plan-run"
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "lifecycle_state": state,
                "mode": "report",
                "roster": [
                    {
                        "name": "fake-security-0",
                        "cli": "fake",
                        "lens": "security",
                        "model": None,
                        "effort": None,
                        "scope": "doc",
                        "timeout": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = claims if claims is not None else [_claim("c-0001@1", severity="high")]
    (run / "claims.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    (run / "report.md").write_text("review report", encoding="utf-8")
    round_dir = run / "round-1"
    round_dir.mkdir()
    (round_dir / "fake-security-0.json").write_text("{}", encoding="utf-8")
    return root, run


def test_plan_writes_claim_linked_proposal_without_mutating_inputs(tmp_path, capsys):
    root, run = _terminal_run(tmp_path)
    repo_file = tmp_path / "app.py"
    repo_file.write_text("source stays untouched", encoding="utf-8")
    secret = "transcript secret must not reach PLAN.md"
    for suffix in ("raw", "prompt", "err"):
        (run / "round-1" / f"fake-security-0.{suffix}").write_text(secret, encoding="utf-8")
    (run / "report.md").write_text(secret, encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in [
            run / "run.json",
            run / "claims.jsonl",
            run / "report.md",
            run / "round-1" / "fake-security-0.json",
            run / "round-1" / "fake-security-0.raw",
            run / "round-1" / "fake-security-0.prompt",
            run / "round-1" / "fake-security-0.err",
            repo_file,
        ]
    }

    assert cli.main(["plan", run.name, "--out", str(root)]) == 0

    proposal = (run / "PLAN.md").read_text(encoding="utf-8")
    assert "Proposal — review before implementation" in proposal
    assert "This proposal is non-mutating" in proposal
    assert f"Source run: `{run.name}`" in proposal
    assert "c-0001@1" in proposal
    assert str(run / "claims.jsonl") in proposal
    assert str(run / "report.md") in proposal
    assert str(run / "round-1" / "fake-security-0.json") in proposal
    assert secret not in proposal
    assert {path: path.read_bytes() for path in before} == before
    assert str(run / "PLAN.md") in capsys.readouterr().out


def test_plan_refuses_an_existing_artifact_without_overwriting(tmp_path, capsys):
    root, run = _terminal_run(tmp_path)
    existing = run / "PLAN.md"
    existing.write_text("preserve audit history", encoding="utf-8")

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2

    assert existing.read_text(encoding="utf-8") == "preserve audit history"
    assert "already exists" in capsys.readouterr().err


def test_plan_omits_settled_refuted_and_has_stable_claim_order(tmp_path):
    root, run = _terminal_run(
        tmp_path,
        claims=[
            _claim("c-0002@1", severity="low"),
            _claim("c-0001@1", severity="high"),
            _claim("c-0003@1", severity="critical"),
        ],
    )
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    meta["claim_states"] = {"c-0003@1": "settled-refuted"}
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")

    assert cli.main(["plan", run.name, "--out", str(root)]) == 0

    proposal = (run / "PLAN.md").read_text(encoding="utf-8")
    assert "c-0003@1" not in proposal
    assert proposal.index("c-0001@1") < proposal.index("c-0002@1")


def test_plan_writes_a_valid_empty_checklist_for_zero_claims(tmp_path):
    root, run = _terminal_run(tmp_path, claims=[])

    assert cli.main(["plan", run.name, "--out", str(root)]) == 0

    proposal = (run / "PLAN.md").read_text(encoding="utf-8")
    assert "No unresolved canonical claims were recorded." in proposal


def test_plan_refuses_nonterminal_or_malformed_runs(tmp_path, capsys):
    root, run = _terminal_run(tmp_path, state="running")

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2
    assert not (run / "PLAN.md").exists()
    assert "terminal" in capsys.readouterr().err

    meta = run / "run.json"
    meta.write_text("not json", encoding="utf-8")
    assert cli.main(["plan", run.name, "--out", str(root)]) == 2
    assert not (run / "PLAN.md").exists()


def test_plan_requires_terminal_run_json_even_when_events_report_finished(tmp_path):
    root, run = _terminal_run(tmp_path, state="running")
    finished = EventRecord.create(
        "run_finished",
        {"status": "completed", "next_action": "inspect_report"},
        run_id=run.name,
        timestamp="2026-09-07T12:00:00Z",
    )
    (run / "events.jsonl").write_text(json.dumps(finished.to_dict()) + "\n", encoding="utf-8")

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2

    assert not (run / "PLAN.md").exists()


def test_plan_requires_a_safe_parsed_evidence_path_for_each_unresolved_claim(tmp_path):
    root, run = _terminal_run(tmp_path)
    (run / "round-1" / "fake-security-0.json").unlink()

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2

    assert not (run / "PLAN.md").exists()


def test_plan_rejects_a_symlinked_parsed_evidence_path(tmp_path):
    root, run = _terminal_run(tmp_path)
    parsed = run / "round-1" / "fake-security-0.json"
    parsed.unlink()
    target = tmp_path / "parsed.json"
    target.write_text("{}", encoding="utf-8")
    parsed.symlink_to(target)

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2

    assert not (run / "PLAN.md").exists()


def test_plan_never_reads_or_renders_transcript_content(monkeypatch, tmp_path):
    root, run = _terminal_run(tmp_path)
    secret = "forbidden transcript content"
    transcript_paths = [
        run / "round-1" / "fake-security-0.raw",
        run / "round-1" / "fake-security-0.prompt",
        run / "round-1" / "fake-security-0.err",
    ]
    for path in transcript_paths:
        path.write_text(secret, encoding="utf-8")
    loaded: list[Path] = []
    original_read = status.secure_read_bytes

    def record_read(path, **kwargs):
        loaded.append(Path(path))
        return original_read(path, **kwargs)

    monkeypatch.setattr(status, "secure_read_bytes", record_read)

    assert cli.main(["plan", run.name, "--out", str(root)]) == 0

    proposal = (run / "PLAN.md").read_text(encoding="utf-8")
    assert secret not in proposal
    assert not set(transcript_paths) & set(loaded)


def test_plan_refuses_a_symlinked_plan_artifact(tmp_path, capsys):
    root, run = _terminal_run(tmp_path)
    target = tmp_path / "outside.md"
    target.write_text("outside", encoding="utf-8")
    (run / "PLAN.md").symlink_to(target)

    assert cli.main(["plan", run.name, "--out", str(root)]) == 2

    assert target.read_text(encoding="utf-8") == "outside"
    # POSIX refuses the exclusive create; Windows' name-based walk refuses the
    # reparse point first. Either way nothing is written through the link.
    err = capsys.readouterr().err
    assert "already exists" in err or "symlink or reparse point" in err
