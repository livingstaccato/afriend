"""The frozen artifact stays bound to its exact blob in the saved commit."""

import dataclasses
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from e2e_helpers import AF, _env, run_af
import pytest

from afriend import snapshots
from afriend.errors import UsageError
from afriend.snapshots import SnapshotIdentity

pytestmark = pytest.mark.git


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _identity(tmp_path, *, nested: bool = True):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    source = repo / "nested" / "spec.md" if nested else repo / "spec.md"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(b"# committed contract\n")
    frozen = tmp_path / "frozen.md"
    frozen.write_bytes(source.read_bytes())
    digest = "sha256:" + hashlib.sha256(frozen.read_bytes()).hexdigest()
    identity = SnapshotIdentity.create(repo, frozen, digest, source_artifact=source)
    return repo, source, frozen, identity


def test_resume_rechecks_frozen_bytes_against_the_saved_commit_blob(tmp_path):
    _repo, _source, frozen, identity = _identity(tmp_path)
    tampered = b"# attacker-controlled replacement\n"
    frozen.write_bytes(tampered)
    coordinated = dataclasses.replace(
        identity,
        artifact_hash="sha256:" + hashlib.sha256(tampered).hexdigest(),
    )

    with pytest.raises(UsageError, match=r"commit artifact.*frozen artifact"):
        coordinated.verify(frozen)


def test_unbound_repo_snapshot_resume_never_reads_a_commit_blob(monkeypatch, tmp_path):
    repo, _source, frozen, _bound_identity = _identity(tmp_path)
    digest = "sha256:" + hashlib.sha256(frozen.read_bytes()).hexdigest()
    identity = SnapshotIdentity.create(repo, frozen, digest)
    identity = SnapshotIdentity.from_meta({"snapshot": identity.to_dict()})

    def unexpected_blob_lookup(*_args):
        raise AssertionError("unbound snapshot read a commit blob")

    monkeypatch.setattr(snapshots, "_resume_commit_blob", unexpected_blob_lookup)

    assert identity.verify(frozen).artifact_bound_to_snapshot is False


def test_a_snapshot_without_the_binding_field_infers_it_from_source_path(tmp_path):
    _repo, _source, frozen, identity = _identity(tmp_path)
    raw = identity.to_dict()
    raw.pop("artifact_bound_to_snapshot")

    restored = SnapshotIdentity._from_dict(raw)

    assert restored.artifact_bound_to_snapshot
    assert restored.verify(frozen) == identity


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"artifact_bound_to_snapshot": True, "source_path": None}, "source_path"),
        ({"artifact_bound_to_snapshot": False}, "source_path"),
        (
            {"artifact_bound_to_snapshot": True, "repo_root": None, "commit": None, "tree": None},
            "repository",
        ),
    ],
)
def test_inconsistent_saved_binding_metadata_is_refused(tmp_path, changes, message):
    repo, _source, _frozen, identity = _identity(tmp_path)
    raw = {**identity.to_dict(), **changes}

    with pytest.raises(UsageError, match=message):
        SnapshotIdentity.from_meta(
            {
                "snapshot": raw,
                "repo_root": str(repo),
                "snapshot_sha": identity.commit,
                "artifact_path": identity.artifact_path,
                "artifact_hash": identity.artifact_hash,
            }
        )


def test_symlinked_source_persists_the_bound_target_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    target = repo / "docs" / "contract.md"
    target.parent.mkdir()
    target.write_bytes(b"# target bytes\n")
    source = repo / "spec.md"
    source.symlink_to(target)
    frozen = tmp_path / "frozen.md"
    frozen.write_bytes(target.read_bytes())
    digest = "sha256:" + hashlib.sha256(frozen.read_bytes()).hexdigest()

    identity = SnapshotIdentity.create(repo, frozen, digest, source_artifact=source)

    assert identity.source_path == "docs/contract.md"
    source.unlink()
    assert SnapshotIdentity._from_dict(identity.to_dict()).verify(frozen) == identity


@pytest.mark.parametrize(
    "source_path",
    ["/etc/passwd", "../spec.md", ".", "nested/../spec.md", "nested//spec.md", "\0spec.md"],
)
def test_hostile_saved_source_binding_is_refused(source_path, tmp_path):
    _repo, _source, _frozen, identity = _identity(tmp_path)
    raw = identity.to_dict()
    raw["source_path"] = source_path

    with pytest.raises(UsageError, match=r"source_path.*repository-relative"):
        SnapshotIdentity.from_meta({"snapshot": raw})


def test_symlinked_invocation_tamper_does_not_rewrite_resume_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    docs = repo / "docs"
    docs.mkdir()
    artifact = docs / "spec.md"
    artifact.write_text("# repository contract\n")
    linkdir = repo / "linkdir"
    linkdir.symlink_to("docs")
    invoked = linkdir / "spec.md"
    halted = run_af(
        tmp_path,
        invoked,
        "--friend",
        "fake:judge_uphold_a",
        "--friend",
        "fake:judge_uphold_b",
        "--merge",
        "orchestrator",
    )
    assert halted.returncode == 10, halted.stderr
    run_dir = next((tmp_path / "runs").iterdir())
    request = run_dir / "round-1" / "REQUEST.json"
    response = json.loads(request.read_text())
    response["merges"] = []
    response_path = request.parent / "RESPONSE.json"
    response_path.write_text(json.dumps(response))
    frozen = next((run_dir / "artifact").iterdir())
    tampered = b"# coordinated replacement\n"
    frozen.write_bytes(tampered)
    digest = "sha256:" + hashlib.sha256(tampered).hexdigest()
    run_json = run_dir / "run.json"
    meta = json.loads(run_json.read_text())
    meta["artifact_hash"] = digest
    meta["artifact_path"] = str(invoked)
    meta["snapshot"]["artifact_hash"] = digest
    meta["snapshot"]["source_path"] = None
    meta["snapshot_history"][-1]["artifact_hash"] = digest
    meta["snapshot_history"][-1]["source_path"] = None
    run_json.write_text(json.dumps(meta, indent=2, sort_keys=True))
    before = run_json.read_bytes()
    before_response = response_path.read_bytes()
    report = run_dir / "report.md"
    before_report = report.read_bytes()

    resumed = subprocess.run(
        [
            sys.executable,
            str(AF),
            "run",
            "--resume",
            run_dir.name,
            "--out",
            str(tmp_path / "runs"),
        ],
        capture_output=True,
        text=True,
        env=_env(),
    )

    assert resumed.returncode == 2, resumed.stderr
    assert "artifact_bound_to_snapshot requires source_path" in resumed.stderr
    assert run_json.read_bytes() == before
    assert response_path.read_bytes() == before_response
    assert report.read_bytes() == before_report
