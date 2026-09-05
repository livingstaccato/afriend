"""Current documentation for confined repository-review access."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AFRIEND = REPO / "src" / "afriend" / "assets" / "entrypoints" / "afriend"
OPERATOR_DOCS = [AFRIEND / "SKILL.md", *(AFRIEND / "references").glob("*.md")]


def test_modes_docs_distinguish_access_failure_from_discard():
    modes = (AFRIEND / "references" / "modes.md").read_text().lower()

    assert "not assessed — judge access failure" in modes
    assert "working judges repeatedly had access to the evidence" in modes


def test_operator_docs_explain_codex_outer_readonly_and_remote_tool_denial():
    docs = " ".join(path.read_text().lower() for path in OPERATOR_DOCS)

    assert "macos command sandbox cannot nest" in docs
    assert "built-in browser, computer, and web-search tools" in docs
