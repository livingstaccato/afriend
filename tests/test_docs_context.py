"""Documentation contract tests for host-resolved review context."""

import html
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]
ENTRYPOINTS = REPO / "src" / "afriend" / "assets" / "entrypoints"


def _svg_visible_text(svg_path: Path) -> str:
    """Read rendered labels without coupling this focused suite to test_docs."""
    raw = svg_path.read_text()
    joined = " ".join(html.unescape(m) for m in re.findall(r"<text[^>]*>([^<]*)</text>", raw))
    return " ".join(joined.split())


def test_current_docs_explain_bounded_review_context_composition_and_protocol():
    readme = " ".join(REPO.joinpath("README.md").read_text().lower().split())
    docs = " ".join((REPO / "docs" / "README.md").read_text().lower().split())
    architecture = " ".join(
        (REPO / "docs" / "architecture" / "README.md").read_text().lower().split()
    )

    for phrase in (
        "afriend context show",
        "afriend context set",
        "--sources current-task",
        "--automatic-combine",
        "--ambiguity ask",
        "host-visible explicit evidence",
        "explicit supplied artifact is authoritative",
        "unmarked artifacts ignore adjacent json",
        "marked composites require a valid bound manifest",
        "does not grant repository, provider, external-tool, or write authority",
    ):
        assert phrase in readme, phrase
    assert "host-session resolver" in docs
    assert "deterministic, content-bound composite" in docs
    assert "normal run then creates the snapshot and frozen artifacts/resume path" in architecture


def test_readme_first_review_preflight_covers_standalone_and_composed_contexts():
    readme = REPO.joinpath("README.md").read_text()
    start = readme.index("On the first review request in a host task")
    end = readme.index("The built-in profiles", start)
    preflight = " ".join(readme[start:end].lower().split())

    for phrase in (
        "standalone artifact",
        "intent",
        "every selected plan, review, and change member",
        "repository",
        "profile/mode",
        "friends",
        "downgrade",
        "cancel, changes only, review only, plan only",
        "change the profile or mode",
    ):
        assert phrase in preflight, phrase


def test_live_docs_describe_composer_output_as_content_bound_until_run_freezes_it():
    current = {
        "README.md": REPO / "README.md",
        "docs/README.md": REPO / "docs" / "README.md",
        "architecture README": REPO / "docs" / "architecture" / "README.md",
        "router skill": ENTRYPOINTS / "afriend" / "SKILL.md",
        "review skill": ENTRYPOINTS / "review" / "SKILL.md",
    }
    text = {name: " ".join(path.read_text().lower().split()) for name, path in current.items()}

    assert "replaceable before run" in text["README.md"]
    assert "frozen run-owned artifact and manifest copies" in text["README.md"]
    for name, value in text.items():
        assert "immutable composite" not in value, name


def test_architecture_index_orders_preflight_before_run_snapshot():
    architecture = " ".join(
        (REPO / "docs" / "architecture" / "README.md").read_text().lower().split()
    )

    assert "preflight precedes dispatch" in architecture
    assert "normal run then creates the snapshot and frozen artifacts/resume path" in architecture
    assert "before `/afriend` preflight" not in architecture


def test_skill_routing_diagram_includes_preflight_events_and_read_only_status():
    source = (REPO / "docs" / "architecture" / "skill-routing.puml").read_text()
    visible = _svg_visible_text(REPO / "docs" / "architecture" / "skill-routing.svg")
    for label in ("session preflight", "events.jsonl", "afriend status"):
        assert label in source
        assert label in visible


def test_skill_routing_diagram_shows_review_context_composition_path():
    source = (REPO / "docs" / "architecture" / "skill-routing.puml").read_text().lower()
    visible = _svg_visible_text(REPO / "docs" / "architecture" / "skill-routing.svg").lower()
    for label in (
        "host-session resolver",
        "cli composer",
        "deterministic, content-bound composite + manifest",
        "normal run snapshot / resume",
    ):
        assert label in source
        assert label in visible
