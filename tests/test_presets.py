"""Tests for effort presets (spec §10, §10.1, §18.8)."""

import pytest

from afriend import presets
from afriend.adapters import load_adapters
from afriend.paths import ADAPTER_DIR


@pytest.fixture
def registry():
    return load_adapters(ADAPTER_DIR)


def test_inherit_emits_nothing(registry):
    """The default, and the whole "inherit, don't override" policy: each CLI
    carries an effort its owner chose, and overriding silently produces
    surprise behaviour and surprise cost."""
    for adapter in registry.values():
        assert presets.effort_for(presets.INHERIT, adapter) is None


def test_thorough_takes_the_best_each_adapter_actually_has(registry):
    """ "Maximum *available* effort per friend" -- uneven by construction, and
    that unevenness is why the report states what each friend received."""
    assert presets.effort_for(presets.THOROUGH, registry["claude"]) == "max"
    assert presets.effort_for(presets.THOROUGH, registry["codex"]) == "xhigh"
    # agy tops out at high; naming a fixed key would refuse to run instead.
    assert presets.effort_for(presets.THOROUGH, registry["agy"]) == "high"


def test_cheap_takes_the_lowest(registry):
    for name in ("claude", "codex", "agy"):
        assert presets.effort_for(presets.CHEAP, registry[name]) == "low"


def test_an_adapter_with_no_effort_levels_gets_none(registry):
    """ollama is a bare model behind an endpoint and has no such concept."""
    assert presets.effort_for(presets.THOROUGH, registry["ollama"]) is None


def test_every_selected_level_is_one_the_adapter_declares(registry):
    """A level build_argv does not recognise raises UsageError, so a preset
    that picked one would turn "run thoroughly" into "refuse to run"."""
    for preset in (presets.THOROUGH, presets.CHEAP):
        for adapter in registry.values():
            level = presets.effort_for(preset, adapter)
            assert level is None or level in adapter.effort


def test_gate_defaults_to_thorough():
    """§7's mode table. It is the mode that fails a build."""
    assert presets.default_preset("gate") == presets.THOROUGH


def test_every_other_mode_inherits():
    for mode in ("report", "crossexam", "loop"):
        assert presets.default_preset(mode) == presets.INHERIT


def test_an_unverifiable_adapter_is_called_out(registry):
    """Pi accepts invalid thinking levels with a warning and keeps running."""
    note = presets.unverifiable_note(presets.THOROUGH, registry["pi"])
    assert note is not None and "unverified" in note


def test_a_verifiable_adapter_needs_no_note(registry):
    assert presets.unverifiable_note(presets.THOROUGH, registry["claude"]) is None


def test_inherit_never_produces_notes(registry):
    for adapter in registry.values():
        assert presets.unverifiable_note(presets.INHERIT, adapter) is None
        assert presets.no_effort_note(presets.INHERIT, adapter) is None


def test_an_adapter_with_no_effort_says_so(registry):
    note = presets.no_effort_note(presets.CHEAP, registry["ollama"])
    assert note is not None and "no effort levels" in note


@pytest.mark.parametrize("preset", [presets.CHEAP, presets.THOROUGH])
@pytest.mark.parametrize("model", [None, "openai/gpt-5.6-sol"])
def test_opencode_presets_resolve_and_build_without_unsupported_flags(
    registry, tmp_path, monkeypatch, preset, model
):
    from afriend import adapters, cli
    from afriend.authority import ExternalToolPolicy
    from afriend.commands import friends

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(friends.execresolve, "safe_which", lambda _binary: "/bin/opencode")
    flags = [
        "run",
        "spec.md",
        "--friend",
        "opencode:security",
        "--preset",
        preset,
        "--allow-external-tools=opencode",
    ]
    if model is not None:
        flags += ["--model", model]
    args = cli.build_parser().parse_args(flags)
    downgrades = []
    resolved = friends.resolve_friends(args, registry, None, downgrades)
    assert len(resolved.specs) == 1
    spec = resolved.specs[0]
    assert spec.effort is None
    assert spec.model == model
    assert any("opencode has no effort levels" in note for note in downgrades)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Review this")
    argv, _, capability = adapters.build_argv(
        registry["opencode"],
        spec,
        prompt_file=prompt,
        schema_file=tmp_path / "schema.json",
        external_tool_policy=ExternalToolPolicy.ALLOW,
    )
    assert "--variant" not in argv
    assert capability.effort == "none"
    if model is None:
        assert "--model" not in argv
    else:
        assert argv[argv.index("--model") + 1] == model
