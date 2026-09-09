import argparse
import json
from pathlib import Path

import pytest

from afriend.authority import ExternalToolPolicy
from afriend.cliargs import build_parser
from afriend.commands import setup
from afriend.commands.runmeta import _restore_args
from afriend.commands.runmeta_schema import CURRENT_SCHEMA_VERSION
from afriend.errors import UsageError


def _write_resume_fixture(
    tmp_path: Path,
    invocation: dict[str, object],
    roster: list[dict[str, object]] | None = None,
) -> Path:
    run_dir = tmp_path / "run-test"
    run_dir.mkdir()
    artifact = str(tmp_path / "spec.md")
    snapshot = {
        "repo_root": None,
        "commit": None,
        "tree": None,
        "artifact_path": artifact,
        "artifact_hash": "sha256:" + "0" * 64,
        "predecessor": None,
    }
    meta = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "lifecycle_state": "waiting-for-orchestrator",
        "invocation": {"artifact": artifact, "friend": [], **invocation},
        # The audit copy of the grants and the invocation that produced them
        # must agree, and resume refuses the run when they do not. The current
        # schema writes both, so a fixture states both.
        "external_tool_grants": sorted(invocation.get("allow_external_tools") or []),
        "roster": roster or [],
        "snapshot": snapshot,
        "snapshot_history": [snapshot],
        # Quorum is cross-checked against the friend audit rows, so a fixture
        # states it. Tests that supply audit rows override this.
        "successful_friend_ids": [],
    }
    (tmp_path / "spec.md").write_text("# spec\n")
    round_dir = run_dir / "round-1"
    round_dir.mkdir()
    (round_dir / "REQUEST.json").write_text(json.dumps({"question": "merge"}))
    (run_dir / "run.json").write_text(json.dumps(meta))
    return run_dir


def test_resume_preserves_reasserted_unused_external_tool_grant_with_empty_registry(
    tmp_path, monkeypatch
):
    run_dir = _write_resume_fixture(tmp_path, {"allow_external_tools": ["future"]})

    restored = _restore_args(
        build_parser().parse_args(
            [
                "run",
                "--resume",
                str(run_dir),
                "--allow-external-tools=future",
                "--no-progress",
            ]
        )
    )

    monkeypatch.setattr(setup, "load_adapters", lambda _path: {})
    monkeypatch.setattr(setup, "install_abort_handlers", lambda *_args: {})

    prepared = setup.prepare_run(restored)

    assert prepared.registry == {}
    assert prepared.specs == []
    assert prepared.authority_policy.for_provider("future") is ExternalToolPolicy.ALLOW
    assert prepared.authority_policy.for_provider("other") is ExternalToolPolicy.DENY


def test_fresh_external_tool_grant_is_rejected_against_empty_adapter_registry(monkeypatch):
    monkeypatch.setattr(setup, "load_adapters", lambda _path: {})

    with pytest.raises(UsageError, match="unknown --allow-external-tools"):
        setup.prepare_run(argparse.Namespace(allow_external_tools=["future"]))
