import json
from pathlib import Path

import pytest

from afriend import reviewprofiles, sessionconfig
from afriend.errors import UsageError


def test_missing_session_config_defaults_to_quick(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    config = sessionconfig.load(reviewprofiles.names())

    assert config.default_profile == "quick"
    assert config.review_context == sessionconfig.ReviewContextConfig(
        enabled=True,
        sources="current-task",
        automatic_combine=True,
        ambiguity="ask",
    )
    assert not sessionconfig.config_path().exists()


def test_set_default_round_trips_with_atomic_json_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    sessionconfig.set_default("balanced", known=reviewprofiles.names())

    assert sessionconfig.load(reviewprofiles.names()).default_profile == "balanced"
    assert json.loads(sessionconfig.config_path().read_text(encoding="utf-8")) == {
        "default_profile": "balanced",
        "profiles": {},
        "review_context": {
            "ambiguity": "ask",
            "automatic_combine": True,
            "enabled": True,
            "sources": "current-task",
        },
        "version": 3,
    }
    assert list(sessionconfig.config_path().parent.glob("*.tmp")) == []


def test_review_context_partial_update_round_trips_and_preserves_session_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sessionconfig.create_profile("ci", "quick", {"timeout": 60})
    sessionconfig.set_default("ci")

    sessionconfig.set_review_context(sources="recent-session", ambiguity="newest")

    config = sessionconfig.load()
    assert config.default_profile == "ci"
    assert config.profiles == {"ci": {"base": "quick", "timeout": 60}}
    assert config.review_context == sessionconfig.ReviewContextConfig(
        enabled=True,
        sources="recent-session",
        automatic_combine=True,
        ambiguity="newest",
    )
    assert json.loads(sessionconfig.config_path().read_text(encoding="utf-8"))[
        "review_context"
    ] == {
        "enabled": True,
        "sources": "recent-session",
        "automatic_combine": True,
        "ambiguity": "newest",
    }


@pytest.mark.parametrize(
    ("contents", "field"),
    [
        (
            '{"version": 3, "default_profile": "quick", "profiles": {}, '
            '"review_context": {"enabled": true, "sources": "current-task", '
            '"automatic_combine": true, "ambiguity": "ask", "extra": true}}',
            "review_context.*keys",
        ),
        (
            '{"version": 3, "default_profile": "quick", "profiles": {}, '
            '"review_context": {"enabled": 1, "sources": "current-task", '
            '"automatic_combine": true, "ambiguity": "ask"}}',
            "review_context.enabled.*boolean",
        ),
        (
            '{"version": 3, "default_profile": "quick", "profiles": {}, '
            '"review_context": {"enabled": true, "sources": "current-task", '
            '"automatic_combine": 1, "ambiguity": "ask"}}',
            "review_context.automatic_combine.*boolean",
        ),
        (
            '{"version": 3, "default_profile": "quick", "profiles": {}, '
            '"review_context": {"enabled": true, "sources": "all-history", '
            '"automatic_combine": true, "ambiguity": "ask"}}',
            "review_context.sources.*one of",
        ),
        (
            '{"version": 3, "default_profile": "quick", "profiles": {}, '
            '"review_context": {"enabled": true, "sources": "current-task", '
            '"automatic_combine": false, "ambiguity": "silent"}}',
            "review_context.ambiguity.*one of",
        ),
    ],
)
def test_review_context_schema_is_strict(tmp_path, monkeypatch, contents, field):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = sessionconfig.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(UsageError, match=field):
        sessionconfig.load()


@pytest.mark.parametrize(
    "contents",
    [
        '{"version": 1, "default_profile": "balanced"}',
        '{"version": 2, "default_profile": "quick", "profiles": {}}',
    ],
)
def test_pre_review_context_session_schemas_load_with_safe_policy(tmp_path, monkeypatch, contents):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = sessionconfig.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(contents, encoding="utf-8")

    assert sessionconfig.load().review_context == sessionconfig.ReviewContextConfig()


def test_set_default_refuses_an_unknown_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(UsageError, match=r"default_profile.*one of.*quick"):
        sessionconfig.set_default("unsafe", known=reviewprofiles.names())

    assert not sessionconfig.config_path().exists()


def test_config_path_honors_absolute_xdg_home_and_rejects_relative(tmp_path, monkeypatch):
    absolute = tmp_path / "absolute-config"
    assert sessionconfig.config_path({"XDG_CONFIG_HOME": str(absolute)}) == (
        absolute / "afriend" / "session.json"
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert sessionconfig.config_path({"XDG_CONFIG_HOME": ".relative-config"}) == (
        tmp_path / "home" / ".config" / "afriend" / "session.json"
    )


@pytest.mark.parametrize(
    ("contents", "field"),
    [
        ("not json", "malformed JSON"),
        ("[]", "top-level"),
        ('{"version": 1}', "top-level keys"),
        ('{"version": 1, "default_profile": "quick", "provider": "codex"}', "top-level keys"),
        ('{"version": 2, "default_profile": "quick"}', "version"),
        ('{"version": 1, "default_profile": 7}', "default_profile"),
        ('{"version": 1, "default_profile": "unknown"}', "default_profile"),
    ],
)
def test_malformed_session_contract_is_rejected(tmp_path, monkeypatch, contents, field):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = sessionconfig.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(UsageError, match=rf"session.json.*{field}"):
        sessionconfig.load(reviewprofiles.names())


def test_builtin_profiles_only_define_safe_run_defaults():
    assert reviewprofiles.names() == ("balanced", "quick", "thorough")
    assert reviewprofiles.get("quick") == reviewprofiles.ReviewProfile(name="quick", mode="report")
    assert reviewprofiles.get("balanced") == reviewprofiles.ReviewProfile(
        name="balanced", mode="crossexam"
    )
    assert reviewprofiles.get("thorough") == reviewprofiles.ReviewProfile(
        name="thorough", mode="loop"
    )
    assert reviewprofiles.get("unknown") is None
    for profile in reviewprofiles.builtins().values():
        assert tuple(vars(profile)) == ("name", "mode", "settings")
        assert "provider" not in vars(profile)
        assert "friend" not in vars(profile)
        assert "credential" not in vars(profile)
        assert "process" not in vars(profile)
        assert "authority" not in vars(profile)


def test_review_profile_default_settings_are_independent_immutable_mappings():
    first = reviewprofiles.ReviewProfile(name="first", mode="report")
    second = reviewprofiles.ReviewProfile(name="second", mode="report")

    assert first.settings == second.settings == {}
    assert first.settings is not second.settings
    with pytest.raises(TypeError):
        first.settings["timeout"] = 1  # type: ignore[index]


def test_session_config_default_profiles_are_independent_immutable_mappings():
    first = sessionconfig.SessionConfig()
    second = sessionconfig.SessionConfig()

    assert first.profiles == second.profiles == {}
    assert first.profiles is not second.profiles
    with pytest.raises(TypeError):
        first.profiles["ci"] = {}  # type: ignore[index]
