"""The deliberately narrow ``afriend context`` command family."""

import json
from pathlib import Path
import subprocess

import pytest

from afriend import sessionconfig
from afriend.cli import main


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    source = repo / "code.txt"
    source.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "code.txt")
    _git(repo, "commit", "-m", "first")
    base = _git(repo, "rev-parse", "HEAD")
    source.write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second")
    head = _git(repo, "rev-parse", "HEAD")
    source.write_text("dirty\n", encoding="utf-8")
    return repo, base, head


def test_context_show_is_read_only_and_renders_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert main(["context", "show", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "ambiguity": "ask",
        "automatic_combine": True,
        "enabled": True,
        "sources": "current-task",
    }
    assert not sessionconfig.config_path().exists()


def test_context_set_persists_only_the_named_fields(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    sessionconfig.set_review_context(enabled=False, automatic_combine=False)

    assert main(["context", "set", "--sources", "recent-session", "--ambiguity", "newest"]) == 0

    assert sessionconfig.load().review_context == sessionconfig.ReviewContextConfig(
        enabled=False,
        sources="recent-session",
        automatic_combine=False,
        ambiguity="newest",
    )
    assert "review context" in capsys.readouterr().out


def test_context_set_accepts_the_exact_paired_boolean_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert main(["context", "set", "--disabled", "--no-automatic-combine"]) == 0

    assert sessionconfig.load().review_context == sessionconfig.ReviewContextConfig(
        enabled=False,
        sources="current-task",
        automatic_combine=False,
        ambiguity="ask",
    )


def test_context_compose_writes_a_chain_receipt_with_all_change_members(
    repository, tmp_path, capsys
):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    review = tmp_path / "review.md"
    composite = tmp_path / "composite.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    review.write_text("# Review\n", encoding="utf-8")

    assert (
        main(
            [
                "context",
                "compose",
                "--repo",
                str(repo),
                "--out",
                str(composite),
                "--plan",
                str(plan),
                "--review",
                str(review),
                "--worktree-diff",
                "--range",
                f"{base}..{head}",
                "--range",
                f"{head}^..{head}",
                "--json",
            ]
        )
        == 0
    )

    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "composite": str(composite.absolute()),
        "intent": "validate-chain",
        "manifest": str(composite.with_suffix(".md.json").absolute()),
    }
    manifest = json.loads(composite.with_suffix(".md.json").read_text(encoding="utf-8"))
    assert len(manifest["changes"]) == 3


@pytest.mark.parametrize(
    "argv",
    [
        ["context", "compose", "--out", "composite.md", "--plan", "plan.md", "--range", "a..b"],
        ["context", "compose", "--repo", "repo", "--out", "composite.md", "--range", "a..b"],
        ["context", "compose", "--repo", "repo", "--out", "composite.md", "--plan", "plan.md"],
    ],
)
def test_context_compose_rejects_missing_required_shape(argv):
    with pytest.raises(SystemExit, match="2"):
        main(argv)


def test_context_compose_refuses_duplicate_role_sources_before_writing(
    repository, tmp_path, capsys
):
    repo, base, head = repository
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    output = tmp_path / "composite.md"
    first.write_text("# first\n", encoding="utf-8")
    second.write_text("# second\n", encoding="utf-8")

    assert (
        main(
            [
                "context",
                "compose",
                "--repo",
                str(repo),
                "--out",
                str(output),
                "--plan",
                str(first),
                "--plan",
                str(second),
                "--range",
                f"{base}..{head}",
            ]
        )
        == 2
    )

    assert "at most one --plan" in capsys.readouterr().err
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_context_compose_refuses_a_repository_other_than_the_worktree_root(
    repository, tmp_path, capsys
):
    repo, base, head = repository
    plan = tmp_path / "plan.md"
    output = tmp_path / "composite.md"
    plan.write_text("# plan\n", encoding="utf-8")
    child = repo / "child"
    child.mkdir()

    assert (
        main(
            [
                "context",
                "compose",
                "--repo",
                str(child),
                "--out",
                str(output),
                "--plan",
                str(plan),
                "--range",
                f"{base}..{head}",
            ]
        )
        == 2
    )

    assert "exact Git worktree root" in capsys.readouterr().err
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()


def test_context_compose_reports_an_unreadable_source_as_a_usage_refusal(
    repository, tmp_path, capsys
):
    repo, base, head = repository
    output = tmp_path / "composite.md"
    missing = tmp_path / "missing-plan.md"

    assert (
        main(
            [
                "context",
                "compose",
                "--repo",
                str(repo),
                "--out",
                str(output),
                "--plan",
                str(missing),
                "--range",
                f"{base}..{head}",
            ]
        )
        == 2
    )

    assert "cannot compose review context" in capsys.readouterr().err
    assert not output.exists()
    assert not output.with_suffix(".md.json").exists()
