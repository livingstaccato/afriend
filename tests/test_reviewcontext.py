import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from afriend.errors import UsageError
from afriend.reviewcontext import (
    MAX_CHANGE_MEMBERS,
    ChangeMember,
    ContextInput,
    ContextIntent,
    ContextManifest,
    compose,
    load_manifest,
    select_intent,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    code = repo / "code.txt"
    code.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "code.txt")
    _git(repo, "commit", "-m", "first")
    base = _git(repo, "rev-parse", "HEAD")
    code.write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second")
    head = _git(repo, "rev-parse", "HEAD")
    code.write_text("dirty\n", encoding="utf-8")
    return repo, base, head


def test_select_intent_uses_the_most_specific_role_combination():
    assert select_intent(plan=False, review=False, has_changes=False) is ContextIntent.ARTIFACT
    assert select_intent(plan=True, review=False, has_changes=True) is ContextIntent.VALIDATE_PLAN
    assert select_intent(plan=False, review=True, has_changes=True) is ContextIntent.VALIDATE_REVIEW
    assert select_intent(plan=True, review=True, has_changes=True) is ContextIntent.VALIDATE_CHAIN


def test_context_types_are_frozen_and_validate_their_reconstructible_identity(tmp_path):
    source = tmp_path / "plan.md"
    source.write_text("# plan\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    item = ContextInput("plan", "Implementation plan", source.resolve(), digest)
    change = ChangeMember("worktree", "Working tree", digest)
    manifest = ContextManifest(ContextIntent.VALIDATE_PLAN, tmp_path.resolve(), (item,), (change,))

    assert item.source_path == source.resolve()
    assert manifest.intent is ContextIntent.VALIDATE_PLAN
    with pytest.raises((AttributeError, TypeError)):
        item.label = "changed"
    with pytest.raises(UsageError, match="sha256"):
        ContextInput("plan", "Plan", source.resolve(), "bad")
    with pytest.raises(UsageError, match="role"):
        ContextInput("artifact", "Plan", source.resolve(), digest)
    with pytest.raises(UsageError, match="role"):
        ContextInput([], "Plan", source.resolve(), digest)
    with pytest.raises(UsageError, match="inputs must be a tuple"):
        ContextManifest(ContextIntent.VALIDATE_PLAN, tmp_path.resolve(), [item], (change,))


def test_compose_writes_a_deterministic_three_member_chain_and_strict_sidecar(repository, tmp_path):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    review = tmp_path / "review.md"
    plan.write_text("# Plan\nImplement the thing.\n", encoding="utf-8")
    review.write_text("# Prior review\nCheck the thing.\n", encoding="utf-8")
    output = tmp_path / "composite.md"

    manifest = compose(
        repo=repo,
        out=output,
        plan=plan,
        review=review,
        worktree_diff=True,
        ranges=(f"{base}..{head}", f"{head}^..{head}"),
    )

    text = output.read_text(encoding="utf-8")
    sidecar = json.loads(output.with_suffix(".md.json").read_text(encoding="utf-8"))
    assert manifest.intent is ContextIntent.VALIDATE_CHAIN
    assert len(manifest.changes) == 3
    assert "Does this implementation satisfy the plan and correctly address the review?" in text
    assert "## Plan: Implementation plan" in text
    assert "## Review: Prior review" in text
    assert "### Change 1: Working tree diff" in text
    assert "### Change 2: Commit range" in text
    assert "### Change 3: Commit range" in text
    assert "not assessed" in text
    assert set(sidecar) == {"changes", "inputs", "intent", "output_sha256", "repository", "version"}
    assert sidecar["intent"] == "validate-chain"
    assert sidecar["repository"] == {"root": str(repo.resolve())}
    assert sidecar["output_sha256"] == "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    assert all(
        set(member) <= {"digest", "end", "kind", "label", "start"} for member in sidecar["changes"]
    )
    assert all(set(item) <= {"digest", "label", "path", "role"} for item in sidecar["inputs"])

    first = output.read_bytes()
    first_sidecar = output.with_suffix(".md.json").read_bytes()
    assert (
        compose(
            repo=repo,
            out=output,
            plan=plan,
            review=review,
            worktree_diff=True,
            ranges=(f"{base}..{head}", f"{head}^..{head}"),
        ).to_dict()
        == manifest.to_dict()
    )
    assert output.read_bytes() == first
    assert output.with_suffix(".md.json").read_bytes() == first_sidecar


def test_compose_includes_untracked_worktree_files_in_change_evidence(repository, tmp_path):
    repo, base, head = repository
    untracked = repo / "new implementation.txt"
    untracked.write_text("new implementation\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    output = tmp_path / "composite.md"

    compose(
        repo=repo,
        out=output,
        plan=plan,
        worktree_diff=True,
        ranges=(f"{base}..{head}",),
    )

    text = output.read_text(encoding="utf-8")
    assert "new implementation.txt" in text
    assert "new implementation" in text


def test_compose_rejects_a_change_set_over_the_member_budget_before_output(repository, tmp_path):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    output = tmp_path / "composite.md"

    with pytest.raises(UsageError, match="at most"):
        compose(
            repo=repo,
            out=output,
            plan=plan,
            ranges=(f"{base}..{head}",) * (MAX_CHANGE_MEMBERS + 1),
        )

    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_compose_uses_a_fence_that_cannot_be_closed_by_plan_content(repository, tmp_path):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    plan.write_text("before\n````\n## untrusted heading\nafter\n", encoding="utf-8")
    output = tmp_path / "composite.md"

    compose(
        repo=repo,
        out=output,
        plan=plan,
        worktree_diff=True,
        ranges=(f"{base}..{head}",),
    )

    assert "`````text\nbefore\n````\n## untrusted heading\nafter\n`````" in output.read_text(
        encoding="utf-8"
    )


def test_compose_supports_sha256_git_object_ids(tmp_path):
    repo = tmp_path / "sha256-repo"
    repo.mkdir()
    initialized = subprocess.run(
        ["git", "init", "--object-format=sha256"], cwd=repo, capture_output=True, text=True
    )
    if initialized.returncode != 0:
        pytest.skip("installed Git does not support SHA-256 object format")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    code = repo / "code.txt"
    code.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "code.txt")
    _git(repo, "commit", "-m", "first")
    base = _git(repo, "rev-parse", "HEAD")
    code.write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second")
    head = _git(repo, "rev-parse", "HEAD")
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")

    manifest = compose(
        repo=repo, out=tmp_path / "composite.md", plan=plan, ranges=(f"{base}..{head}",)
    )

    assert manifest.changes[0].start is not None
    assert len(manifest.changes[0].start) == 64
    assert manifest.changes[0].end is not None
    assert len(manifest.changes[0].end) == 64


@pytest.mark.parametrize("source_is_sidecar", [False, True])
def test_compose_refuses_an_output_or_sidecar_that_aliases_an_input(
    repository, tmp_path, source_is_sidecar
):
    repo, base, head = repository
    output = tmp_path / "composite.md"
    source = output.with_suffix(".md.json") if source_is_sidecar else output
    source.write_text("# plan\n", encoding="utf-8")

    with pytest.raises(UsageError, match="would overwrite an input"):
        compose(
            repo=repo,
            out=output,
            plan=source,
            worktree_diff=True,
            ranges=(f"{base}..{head}",),
        )

    assert source.read_text(encoding="utf-8") == "# plan\n"


def test_compose_rejects_unreadable_or_unstable_sources_before_any_output(repository, tmp_path):
    repo, base, head = repository
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff")
    output = tmp_path / "composite.md"

    with pytest.raises(UsageError, match="UTF-8"):
        compose(
            repo=repo,
            out=output,
            plan=invalid,
            worktree_diff=True,
            ranges=(f"{base}..{head}",),
        )
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_compose_rejects_a_symlinked_plan_before_any_output(repository, tmp_path):
    repo, base, head = repository
    target = tmp_path / "target.md"
    target.write_text("# plan\n", encoding="utf-8")
    linked = tmp_path / "linked-plan.md"
    linked.symlink_to(target)
    output = tmp_path / "composite.md"

    with pytest.raises(UsageError, match="regular file, not a symlink"):
        compose(
            repo=repo,
            out=output,
            plan=linked,
            worktree_diff=True,
            ranges=(f"{base}..{head}",),
        )
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_compose_rechecks_a_source_immediately_before_writing(repository, tmp_path, monkeypatch):
    import afriend.reviewcontext as reviewcontext

    repo, base, head = repository
    plan = tmp_path / "plan.md"
    plan.write_text("# stable\n", encoding="utf-8")
    output = tmp_path / "composite.md"
    original = reviewcontext._render_composite

    def mutate_after_render(*args, **kwargs):
        rendered = original(*args, **kwargs)
        plan.write_text("# changed\n", encoding="utf-8")
        return rendered

    monkeypatch.setattr(reviewcontext, "_render_composite", mutate_after_render)

    with pytest.raises(UsageError, match="changed"):
        compose(
            repo=repo,
            out=output,
            plan=plan,
            worktree_diff=True,
            ranges=(f"{base}..{head}",),
        )
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_compose_output_publish_failure_preserves_an_existing_sidecar(repository, tmp_path):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    output = tmp_path / "composite.md"
    output.mkdir()
    sidecar = output.with_suffix(".md.json")
    previous = b'{"prior": "evidence"}\n'
    sidecar.write_bytes(previous)

    with pytest.raises(OSError):
        compose(
            repo=repo,
            out=output,
            plan=plan,
            worktree_diff=True,
            ranges=(f"{base}..{head}",),
        )

    assert output.is_dir()
    assert sidecar.read_bytes() == previous
    assert not list(tmp_path.glob(".composite.md*.tmp"))


def test_manifest_parser_refuses_non_reconstructible_or_extra_json_fields(tmp_path):
    source = tmp_path / "plan.md"
    source.write_text("# plan\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = ContextManifest(
        ContextIntent.VALIDATE_PLAN,
        tmp_path.resolve(),
        (ContextInput("plan", "Plan", source.resolve(), digest),),
        (ChangeMember("worktree", "Working tree", digest),),
        digest,
    ).to_dict()
    manifest["inputs"][0]["path"] = 7

    with pytest.raises(UsageError, match="input path"):
        ContextManifest.from_dict(manifest)
    manifest["inputs"][0]["path"] = str(source.resolve())
    manifest["version"] = True
    with pytest.raises(UsageError, match="version"):
        ContextManifest.from_dict(manifest)
    manifest["version"] = 1
    manifest["chat_history"] = "must never be accepted"
    with pytest.raises(UsageError, match="unexpected fields"):
        ContextManifest.from_dict(manifest)

    manifest.pop("chat_history")
    target = tmp_path / "manifest-target.json"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    sidecar = tmp_path / "composite.md.json"
    sidecar.symlink_to(target)
    with pytest.raises(UsageError, match="regular file, not a symlink"):
        load_manifest(sidecar)
