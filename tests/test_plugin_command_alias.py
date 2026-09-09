"""`/areview` is a shortcut for the review skill, and has to stay one.

An alias earns its keep only while it points at something. Two ways it stops:
the skill it names gets renamed, or the generated projection under
`plugins/afriend/skills/` grows to cover `commands/` and quietly removes a
file no canonical source produces. Both are silent -- the plugin still loads,
and `/areview` simply does nothing useful -- so they are asserted here.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "afriend"
ALIAS = PLUGIN / "commands" / "areview.md"


def _sync_module():
    path = REPO / "scripts" / "check_plugin_sync.py"
    spec = importlib.util.spec_from_file_location("plugin_sync_alias", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    return dict(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in block.splitlines())
        if key.strip()
    )


def test_the_alias_lives_where_claude_code_discovers_commands():
    """`commands/<name>.md` at the plugin root is what makes it `/areview`.
    A file one directory deeper would become a namespaced command instead."""
    assert ALIAS.is_file()
    assert ALIAS.parent.parent == PLUGIN


def test_the_alias_declares_a_description_and_is_user_invoked_only():
    """Without a description it is unlabelled in `/help`. Model invocation is
    off because the skill is already the model's route -- an alias that both
    the user and the model can take is two doors into one room."""
    front = _frontmatter(ALIAS.read_text(encoding="utf-8"))

    assert front["description"]
    assert front["disable-model-invocation"] == "true"


def test_the_alias_names_a_skill_that_exists_under_that_name():
    """The binding a rename would break: `afriend:review` resolves only while
    a skill declaring `name: review` ships in this plugin."""
    body = ALIAS.read_text(encoding="utf-8")
    skill = PLUGIN / "skills" / "review" / "SKILL.md"

    assert "afriend:review" in body
    assert skill.is_file()
    assert _frontmatter(skill.read_text(encoding="utf-8"))["name"] == "review"


def test_the_alias_forwards_arguments_rather_than_swallowing_them():
    assert "$ARGUMENTS" in ALIAS.read_text(encoding="utf-8")


def test_the_canonical_projection_does_not_claim_the_commands_directory():
    """`commands/` is hand-maintained plugin surface, like the manifests. If a
    projection ever started emitting into it, this file would have two owners."""
    expected = _sync_module().expected_plugin_files()

    assert not any(path.parts[:1] == ("commands",) for path in expected)


def test_a_sync_copy_leaves_a_sibling_commands_directory_alone(tmp_path, monkeypatch):
    """`--copy` replaces `skills/` wholesale. The alias sits beside it, and
    this asserts the replacement stops at that boundary."""
    module = _sync_module()
    plugin = tmp_path / "plugin"
    (plugin / "skills" / "afriend").mkdir(parents=True)
    (plugin / "skills" / "afriend" / "SKILL.md").write_text("stale")
    (plugin / "commands").mkdir()
    alias = plugin / "commands" / "areview.md"
    alias.write_text("alias")
    monkeypatch.setattr(module, "PLUGIN_ROOT", plugin)
    monkeypatch.setattr(module, "SKILLS", plugin / "skills")

    assert module.copy_expected({Path("afriend/SKILL.md"): b"fresh"}) == 0
    assert alias.read_text() == "alias"
    assert (plugin / "skills" / "afriend" / "SKILL.md").read_bytes() == b"fresh"
