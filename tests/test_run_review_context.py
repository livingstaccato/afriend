"""End-to-end provenance, freezing, and resume checks for composed review context."""

import hashlib
import json
import subprocess
import sys

from e2e_helpers import AF, _env, _git_commit, _git_repo, run_af
import pytest

from afriend.commands.reviewcontext import capture_review_context
from afriend.reviewcontext import compose


def _head(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    ).stdout.strip()


def _repository_with_history(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    source = repo / "implementation.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, env=_env())
    _git_commit(repo, "base")
    base = _head(repo)
    source.write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, env=_env())
    _git_commit(repo, "change")
    head = _head(repo)
    source.write_text("value = 3\n", encoding="utf-8")
    return repo, base, head


def _resume_run(tmp_path, run_dir):
    return subprocess.run(
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


def _respond_to_halted_merge(run_dir):
    request = run_dir / "round-1" / "REQUEST.json"
    (request.parent / "RESPONSE.json").write_text(
        request.read_text(encoding="utf-8"), encoding="utf-8"
    )


def _halted_composite_run(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    source = repo / "implementation.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, env=_env())
    _git_commit(repo, "base")
    source.write_text("value = 2\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    composite = tmp_path / "composite.md"
    plan.write_text("# Plan\nValidate implementation.\n", encoding="utf-8")
    compose(repo=repo, out=composite, plan=plan, worktree_diff=True)
    result = run_af(
        tmp_path,
        composite,
        "--repo",
        str(repo),
        "--friend",
        "fake:good:repo",
        "--merge",
        "orchestrator",
    )
    assert result.returncode == 10, result.stderr
    return next((tmp_path / "runs").iterdir())


def _halted_ordinary_run(tmp_path):
    artifact = tmp_path / "ordinary.md"
    artifact.write_text("# ordinary artifact\n", encoding="utf-8")
    result = run_af(tmp_path, artifact, "--friend", "fake:good", "--merge", "orchestrator")
    assert result.returncode == 10, result.stderr
    return next((tmp_path / "runs").iterdir())


def test_capture_ignores_an_unmarked_artifact_before_reading_its_sidecar(tmp_path):
    artifact = tmp_path / "ordinary.md"
    artifact.write_text("# ordinary markdown\n", encoding="utf-8")
    sidecar = artifact.with_suffix(".md.json")
    target = tmp_path / "untrusted.json"
    target.write_text("{}", encoding="utf-8")
    sidecar.symlink_to(target)

    assert capture_review_context(artifact, artifact.read_text(encoding="utf-8")) is None


def test_ordinary_markdown_run_has_no_review_context(tmp_path):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n", encoding="utf-8")

    result = run_af(tmp_path, artifact, "--friend", "fake:good")

    assert result.returncode == 0, result.stderr
    run_dir = next((tmp_path / "runs").iterdir())
    assert "review_context" not in json.loads((run_dir / "run.json").read_text())
    assert not (run_dir / "review-context.json").exists()


def test_run_freezes_a_valid_composer_manifest_without_changing_explicit_repo_scope(tmp_path):
    repo, base, head = _repository_with_history(tmp_path)
    plan = tmp_path / "plan.md"
    review = tmp_path / "review.md"
    composite = tmp_path / "composite.md"
    plan.write_text("# Plan\nMake the value correct.\n", encoding="utf-8")
    review.write_text("# Review\nCheck the value update.\n", encoding="utf-8")
    manifest = compose(
        repo=repo,
        out=composite,
        plan=plan,
        review=review,
        worktree_diff=True,
        ranges=(f"{base}..{head}", f"{head}^..{head}"),
    )
    sidecar = composite.with_suffix(".md.json")
    sidecar_bytes = sidecar.read_bytes()

    result = run_af(
        tmp_path,
        composite,
        "--repo",
        str(repo),
        "--friend",
        "fake:good:repo",
        "--merge",
        "orchestrator",
    )

    assert result.returncode == 10, result.stderr
    run_dir = next((tmp_path / "runs").iterdir())
    frozen_composite = (run_dir / "artifact" / composite.name).read_bytes()
    halted_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert halted_meta["review_context"] == {
        "intent": manifest.intent.value,
        "manifest_digest": "sha256:" + hashlib.sha256(sidecar_bytes).hexdigest(),
        "manifest_path": "review-context.json",
    }
    _respond_to_halted_merge(run_dir)
    composite.write_text("# altered after the halt\n", encoding="utf-8")
    sidecar.write_text('{"untrusted": "live replacement"}', encoding="utf-8")
    resumed = _resume_run(tmp_path, run_dir)

    assert resumed.returncode == 0, resumed.stderr
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    prompt = next((run_dir / "round-1").glob("*.prompt")).read_text(encoding="utf-8")
    assert (run_dir / "artifact" / composite.name).read_bytes() == frozen_composite
    for evidence in (
        "Review intent: validate-chain",
        "### Change 1: Working tree diff",
        "### Change 2: Commit range",
        "### Change 3: Commit range",
    ):
        assert evidence in frozen_composite.decode("utf-8")
        assert evidence in prompt
    assert meta["review_context"] == halted_meta["review_context"]
    assert (run_dir / meta["review_context"]["manifest_path"]).read_bytes() == sidecar_bytes
    assert meta["snapshot"]["repo_root"] == str(repo.resolve())
    assert meta["repository_scope_mode"] == "explicit"


def test_resume_refuses_a_context_run_with_missing_review_context_metadata(tmp_path):
    run_dir = _halted_composite_run(tmp_path)
    _respond_to_halted_merge(run_dir)
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("review_context")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = _resume_run(tmp_path, run_dir)

    assert result.returncode == 2
    assert "review_context" in result.stderr


def test_resume_refuses_forged_context_metadata_for_an_unmarked_frozen_artifact(tmp_path):
    run_dir = _halted_ordinary_run(tmp_path)
    _respond_to_halted_merge(run_dir)
    repo, base, head = _repository_with_history(tmp_path)
    plan = tmp_path / "plan.md"
    composite = tmp_path / "forged-composite.md"
    plan.write_text("# plan\n", encoding="utf-8")
    compose(repo=repo, out=composite, plan=plan, worktree_diff=True, ranges=(f"{base}..{head}",))
    forged_manifest = json.loads(composite.with_suffix(".md.json").read_text(encoding="utf-8"))
    frozen = next((run_dir / "artifact").iterdir())
    forged_manifest["output_sha256"] = "sha256:" + hashlib.sha256(frozen.read_bytes()).hexdigest()
    payload = json.dumps(forged_manifest, sort_keys=True).encode("utf-8")
    (run_dir / "review-context.json").write_bytes(payload)
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["review_context"] = {
        "intent": forged_manifest["intent"],
        "manifest_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "manifest_path": "review-context.json",
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = _resume_run(tmp_path, run_dir)

    assert result.returncode == 2
    assert "marker" in result.stderr
    assert "traceback" not in result.stderr.lower()


def test_resume_refuses_review_context_metadata_with_a_manifest_digest_mismatch(tmp_path):
    run_dir = _halted_composite_run(tmp_path)
    _respond_to_halted_merge(run_dir)
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["review_context"]["manifest_digest"] = "sha256:" + "0" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = _resume_run(tmp_path, run_dir)

    assert result.returncode == 2
    assert "manifest digest" in result.stderr


def test_resume_refuses_a_symlinked_copied_review_context_manifest_cleanly(tmp_path):
    run_dir = _halted_composite_run(tmp_path)
    _respond_to_halted_merge(run_dir)
    copied = run_dir / "review-context.json"
    target = tmp_path / "outside-manifest.json"
    target.write_text("{}", encoding="utf-8")
    copied.unlink()
    copied.symlink_to(target)

    result = _resume_run(tmp_path, run_dir)

    assert result.returncode == 2
    assert "review context manifest" in result.stderr
    assert "traceback" not in result.stderr.lower()


@pytest.mark.parametrize("sidecar_kind", ["malformed", "symlink"])
def test_run_ignores_untrusted_adjacent_json_for_an_ordinary_markdown_artifact(
    tmp_path, sidecar_kind
):
    artifact = tmp_path / "ordinary.md"
    artifact.write_text("# ordinary markdown\n", encoding="utf-8")
    sidecar = artifact.with_suffix(".md.json")
    if sidecar_kind == "malformed":
        sidecar.write_text('{"not": "a composer manifest"}', encoding="utf-8")
    else:
        target = tmp_path / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        sidecar.symlink_to(target)

    result = run_af(tmp_path, artifact, "--friend", "fake:good")

    assert result.returncode == 0, result.stderr
    assert len(list((tmp_path / "runs").iterdir())) == 1


@pytest.mark.parametrize("sidecar_kind", ["missing", "malformed", "symlink"])
def test_run_rejects_a_marked_composite_with_an_invalid_context_sidecar_before_creating_a_run(
    tmp_path, sidecar_kind
):
    artifact = tmp_path / "composite.md"
    artifact.write_text("<!-- afriend-review-context: v1 -->\n# Review context\n", encoding="utf-8")
    sidecar = artifact.with_suffix(".md.json")
    if sidecar_kind == "malformed":
        sidecar.write_text('{"not": "a composer manifest"}', encoding="utf-8")
    elif sidecar_kind == "symlink":
        target = tmp_path / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        sidecar.symlink_to(target)

    result = run_af(tmp_path, artifact, "--friend", "fake:good")

    assert result.returncode == 2
    assert "review context manifest" in result.stderr
    assert not (tmp_path / "runs").exists()


def test_run_rejects_a_marked_sidecar_with_a_nul_path_cleanly(tmp_path):
    repo, base, head = _repository_with_history(tmp_path)
    plan = tmp_path / "plan.md"
    composite = tmp_path / "composite.md"
    plan.write_text("# plan\n", encoding="utf-8")
    compose(repo=repo, out=composite, plan=plan, worktree_diff=True, ranges=(f"{base}..{head}",))
    sidecar = composite.with_suffix(".md.json")
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    manifest["inputs"][0]["path"] = "/tmp/forged\x00path.md"
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_af(tmp_path, composite, "--friend", "fake:good")

    assert result.returncode == 2
    assert "path" in result.stderr
    assert "traceback" not in result.stderr.lower()
    assert not (tmp_path / "runs").exists()


def test_composite_without_a_repository_snapshot_reports_validation_not_assessed(tmp_path):
    repo, base, head = _repository_with_history(tmp_path)
    plan = tmp_path / "plan.md"
    composite = tmp_path / "composite.md"
    plan.write_text("# Plan\nValidate implementation.\n", encoding="utf-8")
    compose(repo=repo, out=composite, plan=plan, ranges=(f"{base}..{head}",))

    result = run_af(tmp_path, composite, "--friend", "fake:good")

    assert result.returncode == 0, result.stderr
    report = next((tmp_path / "runs").iterdir()) / "report.md"
    text = report.read_text(encoding="utf-8").lower()
    assert "implementation validation was not assessed" in text
    assert "implementation validation succeeded" not in text
