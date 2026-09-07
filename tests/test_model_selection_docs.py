"""Documentation contracts for model-selection provenance."""

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "src" / "afriend" / "assets"
ENTRYPOINTS = ASSETS / "entrypoints"
AFRIEND = ENTRYPOINTS / "afriend"
OPERATOR_DOCS = [AFRIEND / "SKILL.md", *(AFRIEND / "references").glob("*.md")]


def _svg_visible_text(svg_path: Path) -> str:
    """Return an SVG's rendered text with XML entities resolved."""
    import html

    raw = svg_path.read_text()
    joined = " ".join(
        html.unescape(match) for match in re.findall(r"<text[^>]*>([^<]*)</text>", raw)
    )
    return " ".join(joined.split())


def test_contract_first_provider_and_authority_guidance_is_shipped():
    docs = {
        "README.md": REPO.joinpath("README.md").read_text(),
        **{path.name: path.read_text() for path in OPERATOR_DOCS},
    }
    joined = " ".join("\n".join(docs.values()).lower().replace("`", "").split())

    for phrase in (
        "host is the orchestrator",
        "--include-self",
        "afriend providers list",
        "afriend providers enable",
        "afriend providers disable",
        "afriend providers set-model",
        "--enable-provider",
        "--disable-provider",
        "disabled providers are not probed",
        "--allow-external-tools",
        "external tools are denied by default",
        "reachable-unconfigured",
        "policy-blocked",
        "snapshot",
    ):
        assert phrase in joined, phrase

    assert "max-loop-iterations" in joined
    assert re.search(r"\bexits? 11\b", joined)


def test_live_markdown_preserves_model_selection_provenance_contract():
    readme = REPO.joinpath("README.md").read_text()
    index = REPO.joinpath("docs", "README.md").read_text()
    router = (AFRIEND / "SKILL.md").read_text()
    configure = (ENTRYPOINTS / "configure" / "SKILL.md").read_text()
    modes = (AFRIEND / "references" / "modes.md").read_text()
    component_source = REPO.joinpath("docs", "architecture", "components.puml").read_text()
    component_svg = _svg_visible_text(REPO / "docs" / "architecture" / "components.svg")

    expected_order = (
        "invocation `--model` > explicit `--friend`/roster > provider "
        "`set-model` > adapter default > CLI default"
    )
    for markdown in (readme, router, modes):
        normalized = " ".join(markdown.split())
        assert expected_order in normalized
        assert (
            "requested and passed to the provider; it is not verified as the backend model"
            in normalized
        )
        assert "no `--model` is passed; the exact model is not verified" in normalized

    assert "afriend run spec.md --friend opencode:security:openai/gpt-5.6-sol" in readme
    assert "`--ignore-user-config`" in router
    assert "model selection provenance" in index.lower()
    assert "Provider `set-model`" in configure
    assert "CLI --> RUN" in component_source
    assert "RUN --> ROSTER : resolve model provenance" in component_source
    assert "model provenance" in component_source
    assert "resolve model provenance" in component_svg
    assert "model provenance" in component_svg
    assert "[installation and plugin troubleshooting](installation-troubleshooting.md)" in index


def test_live_model_provenance_docs_cover_unset_opencode_and_the_startup_flow():
    readme = REPO.joinpath("README.md").read_text()
    router = (AFRIEND / "SKILL.md").read_text()
    modes = (AFRIEND / "references" / "modes.md").read_text()
    component_source = REPO.joinpath("docs", "architecture", "components.puml").read_text()

    unset_opencode = "OpenCode CLI default (no --model passed; exact model not verified)"
    for markdown in (readme, router, modes):
        assert unset_opencode in markdown

    for markdown in (readme, router, modes):
        normalized = " ".join(markdown.split())
        assert "default external-tools-denied policy" in normalized
        assert "`--ignore-user-config`" in normalized
        assert "`--allow-external-tools=codex`" in normalized
        assert "does not supply `--ignore-user-config`" in normalized

    for flow in (
        "commands/friends.py + roster.py\\n<size:11>model provenance + selection</size>",
        "progress.py",
        "RUN --> ROSTER : resolve model provenance",
        "PCONFIG --> ROSTER : provider setting",
        "RUN --> PROGRESS : startup provenance",
        "RUN --> STORE : persist model provenance",
        "STORE --> REPORT : report model provenance",
    ):
        assert flow in component_source
    assert "as MODELS" not in component_source
