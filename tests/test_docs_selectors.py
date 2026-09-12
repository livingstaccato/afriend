"""Which selectors and install metadata this repository still advertises.

Split out of test_docs.py, which crossed the 777-line cap. These share one
question -- what a user or an agent host is told it can invoke -- and it is
a question this repository got wrong once already: removing the router skill
left its `/afriend` selector in a plugin manifest, two skill activation
descriptions, and three docs, because the test guarding it checked a
narrower pattern across a narrower set of files than the removal touched.
"""

import json
from pathlib import Path
import re

from test_docs import _svg_visible_text

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "src" / "afriend" / "assets"
ENTRYPOINTS = ASSETS / "entrypoints"
# `review` is the primary entry: it absorbed the router skill's guidance
# and shared references when that skill was removed.
AFRIEND = ENTRYPOINTS / "review"


def test_no_shipped_file_still_advertises_the_removed_slash_selector():
    """`/afriend` was the router skill's selector, and the router is gone.

    The sibling test below checked `/afriend:` -- with a colon -- across
    three files, so four dead references survived the removal in files it
    never opened: the Codex plugin manifest still offered
    `"/afriend README.md"` as a defaultPrompt, and three docs described
    routing through `/afriend`. A user following any of them types a
    selector that no longer resolves.

    The pattern deliberately excludes a `/afriend` preceded by a word
    character, so repository paths (`plugins/afriend/skills`,
    `github.com/livingstaccato/afriend`, `~/.config/afriend/roster.toml`)
    are not selectors and do not trip it.
    """

    selector = re.compile(r"(?<![\w.-])/afriend(?![\w/-])")
    # CHANGELOG.md is deliberately absent: it records what was true at each
    # release, including the selector this one removes, and rewriting
    # history to satisfy a lint is the opposite of what a changelog is for.
    # Same reasoning as the spec/plan exclusion in the bare-`af` test below.
    shipped = [
        REPO / "README.md",
        REPO / "AGENTS.md",
        *(REPO / "docs").rglob("*.md"),
        *(REPO / "plugins").rglob("*.json"),
        *(REPO / "plugins").rglob("*.md"),
        *(REPO / "src" / "afriend" / "assets").rglob("*.md"),
        *(REPO / "src" / "afriend" / "assets").rglob("*.yaml"),
    ]
    offenders = []
    for path in shipped:
        if "superpowers" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if selector.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()[:90]}")
    assert offenders == [], offenders


def test_current_docs_describe_only_the_four_skill_surface_and_stable_cli():
    current = "\n".join(
        path.read_text()
        for path in (REPO / "README.md", REPO / "AGENTS.md", REPO / "docs" / "README.md")
    ).lower()
    # No `/afriend` selector: it was the router's, and the router is gone.
    assert "/afriend:" not in current
    assert "$afriend:review" in current
    assert "$afriend:afriend" not in current
    assert "$adversarial-friends:" not in current
    assert "afriend status" in current and "afriend review" in current
    assert "afriend doctor" in current and "afriend run" in current
    assert "not executable aliases" in current


def test_current_docs_explain_profiles_guided_setup_events_and_run_status():
    """The public README is the CLI's current user-facing contract."""
    readme = REPO.joinpath("README.md").read_text()
    for phrase in (
        "`quick`",
        "`balanced`",
        "`thorough`",
        "afriend init --guided",
        "afriend init --guided --apply",
        "afriend status <run-id-or-path>",
        "`events.jsonl`",
        "afriend profiles",
        "afriend resolve <run-id> --list",
        "afriend resolve <run-id> --next",
    ):
        assert phrase in readme, phrase


def test_skill_routing_diagram_labels_all_skills_and_commands():
    source = (REPO / "docs" / "architecture" / "skill-routing.puml").read_text()
    visible = _svg_visible_text(REPO / "docs" / "architecture" / "skill-routing.svg")
    for label in ("review", "status", "configure", "resolve"):
        assert label in source
        assert label in visible
    for label in ("afriend run", "afriend doctor", "afriend providers", "afriend resolve"):
        assert label in source
        assert label in visible
    assert "afriend run --resume" in source
    assert "afriend run --resume" in visible


def test_resume_routes_to_run_without_claim_resolution_inputs():
    review_skill = (AFRIEND / "SKILL.md").read_text().lower()
    resolve = " ".join((ENTRYPOINTS / "resolve" / "SKILL.md").read_text().lower().split())
    assert "afriend resume" in review_skill
    assert "afriend run --resume" in review_skill
    assert "afriend run --resume" in resolve
    assert "does not require a disposition or evidence" in resolve
    resume_eval = next(
        case
        for case in json.loads((REPO / "evals" / "evals.json").read_text())["evals"]
        if case["prompt"].startswith("afriend resume")
    )
    assert resume_eval["skill"] == "review"
    assert resume_eval["requires_artifact"] is False
    assert "afriend run --resume" in resume_eval["expected_output"]


def _activation_description(skill: str) -> str:
    """The `description:` a host reads to decide whether to select a skill.

    Only the frontmatter drives activation. Everything else in a SKILL.md is
    read *after* selection, so a routing rule stated in the body cannot make
    the host pick that skill in the first place.
    """
    text = (ENTRYPOINTS / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^description:(.*)$", text, re.MULTILINE)
    assert match, f"{skill}/SKILL.md has no description frontmatter"
    return " ".join(match.group(1).lower().split())


def test_resume_is_claimed_by_review_and_disclaimed_by_status_in_activation_text():
    """The shipped 0.11.0 regression, in the one place that decides routing.

    `status` said it covered "a named existing run", gated behind "explicit
    /afriend routing" -- a selector that was then removed, leaving the gate as
    the far broader "an explicit afriend request". `afriend resume run-123` is
    one, so status swallowed it. Nothing pulled the other way: `review` named
    artifacts and never named resume.

    The rule was written down the whole time, in `review`'s body and in
    `resolve`'s -- and `test_resume_routes_to_run_without_claim_resolution_inputs`
    checked exactly those two bodies. A host never reads them to choose, so
    the eval caught what every text guard missed. This asserts on the text
    that actually routes.
    """
    review = _activation_description("review")
    status = _activation_description("status")

    assert "afriend resume" in review
    assert "afriend resume" in status
    assert "belongs to afriend:review" in status
    assert "never starts, resumes, or changes a run" in status

    # The widening clause is only safe while it is paired with the
    # disclaimer above; an unqualified claim over "a named run" competes
    # with review for every `afriend resume <run-id>`.
    assert "read-only" in status


def test_status_describes_resume_authority_as_current_command_line_grant():
    status = " ".join((ENTRYPOINTS / "status" / "SKILL.md").read_text().lower().split())
    assert "past run's authority record is descriptive only" in status
    assert "same normalized grant is supplied again" in status


def test_plugin_install_metadata_matches_narrow_activation_and_advisory_host_contract():
    plugin_root = REPO / "plugins" / "afriend"
    codex = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text())
    claude = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads((REPO / "plugins" / ".claude-plugin" / "marketplace.json").read_text())
    entry = next(item for item in marketplace["plugins"] if item["name"] == codex["name"])
    descriptions = [
        codex["description"],
        codex["interface"]["shortDescription"],
        codex["interface"]["longDescription"],
        claude["description"],
        marketplace["description"],
        entry["description"],
    ]

    assert marketplace["name"] == "afriend"
    assert claude["name"] == entry["name"] == codex["name"] == "afriend"
    assert claude["version"] == entry["version"]
    assert codex["version"].partition("+")[0] == claude["version"]
    assert codex["interface"]["displayName"] == "afriend"
    for description in descriptions:
        normalized = " ".join(description.lower().split())
        assert "codex" in normalized
        assert "advisory" in normalized
        assert "other agent clis" not in normalized
        assert "independent adversarial reviewers" not in normalized

    # `/afriend README.md` was the first entry until the router skill that
    # owned that selector was removed. It kept being offered as the leading
    # defaultPrompt -- the first thing a Codex user is shown -- for a
    # selector that no longer resolves, and this assertion is what required
    # it to stay.
    prompts = codex["interface"]["defaultPrompt"]
    assert prompts
    assert prompts == [
        "$afriend:review README.md",
        "$afriend:status",
        "$afriend:configure",
        "$afriend:resolve",
    ]


def test_codex_local_marketplace_presents_afriend_and_sources_this_plugin():
    marketplace = json.loads((REPO / ".agents" / "plugins" / "marketplace.json").read_text())
    assert marketplace["name"] == "afriend-local"
    assert marketplace["interface"]["displayName"] == "afriend"
    assert marketplace["plugins"] == [
        {
            "name": "afriend",
            "source": {"source": "local", "path": "./plugins/afriend"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }
    ]
