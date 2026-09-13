"""The no-prompt, no-authority guided setup command."""

import json

import pytest

from afriend import providerconfig, readiness, reviewprofiles, sessionconfig
from afriend.cliargs import build_parser
from afriend.commands import init as init_module
from afriend.errors import NoFriendsError, UsageError
from afriend.paths import ADAPTER_DIR


def _args(*argv: str):
    return build_parser().parse_args(["init", "--guided", *argv])


def _known() -> set[str]:
    return set(init_module.load_adapters(ADAPTER_DIR))


def _ready_codex() -> dict[str, readiness.FriendReadiness]:
    return {
        "codex": readiness.FriendReadiness(
            "codex", readiness.ReadinessState.READY, "available", "/bin/codex", None
        )
    }


def test_guided_preview_is_a_no_write_no_probe_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CODEX_SESSION_ID", "guided-preview")
    roster = tmp_path / "roster.toml"
    roster.write_text("# existing roster\n", encoding="utf-8")
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: pytest.fail("probed"))

    assert (
        init_module.cmd_init(
            _args(
                "--default-profile", "balanced", "--enable-provider", "ollama", "--out", str(roster)
            )
        )
        == 0
    )

    captured = capsys.readouterr()
    output = captured.err
    assert captured.out == ""
    assert "schema version: 1" in output
    assert "default profile: balanced" in output
    assert "enable provider: ollama" in output
    assert "profiles: balanced (crossexam), quick (report), thorough (loop)" in output
    assert "host: codex (host-self-review; advisory=True; independent=False)" in output
    assert "external tools remain denied" in output
    assert "no files were written" in output
    assert roster.read_text(encoding="utf-8") == "# existing roster\n"
    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()


def test_guided_preview_json_is_machine_readable_and_never_writes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for marker in readiness.HOST_ENV_MARKERS:
        monkeypatch.delenv(marker, raising=False)

    assert (
        init_module.cmd_init(
            _args(
                "--json",
                "--disable-provider",
                "opencode",
                "--ollama-model",
                "qwen3:8b",
                "--enable-provider",
                "ollama",
            )
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["guided"] is True
    assert payload["apply"] is False
    assert payload["changes"] == {
        "providers": {
            "ollama": {"enabled": True, "model": "qwen3:8b"},
            "opencode": {"enabled": False},
        }
    }
    assert payload["external_tools"] == "denied"
    assert payload["profiles"] == [
        {"mode": "crossexam", "name": "balanced"},
        {"mode": "report", "name": "quick"},
        {"mode": "loop", "name": "thorough"},
    ]
    assert {row["name"] for row in payload["providers"]} == _known()
    assert payload["host"] is None
    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()


def test_guided_review_context_preview_and_apply_only_touch_selected_settings(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: _ready_codex())

    assert (
        init_module.cmd_init(
            _args(
                "--json",
                "--review-context-sources",
                "recent-session",
                "--review-context-ambiguity",
                "refuse",
            )
        )
        == 0
    )

    preview = json.loads(capsys.readouterr().out)
    assert preview["changes"] == {
        "review_context": {"ambiguity": "refuse", "sources": "recent-session"}
    }
    assert not sessionconfig.config_path().exists()

    assert (
        init_module.cmd_init(
            _args(
                "--apply",
                "--review-context-sources",
                "recent-session",
                "--review-context-ambiguity",
                "refuse",
            )
        )
        == 0
    )

    assert sessionconfig.load().review_context == sessionconfig.ReviewContextConfig(
        enabled=True,
        sources="recent-session",
        automatic_combine=True,
        ambiguity="refuse",
    )


def test_guided_review_context_rejects_an_invalid_selection_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(UsageError, match=r"review_context.sources.*one of"):
        init_module.cmd_init(_args("--review-context-sources", "all-history"))

    assert not sessionconfig.config_path().exists()


def test_guided_apply_changes_only_selected_settings_and_preserves_others(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: _ready_codex())
    known = _known()
    providerconfig.set_enabled("opencode", False, known=known)
    providerconfig.set_model("opencode", "gpt-5.6-sol", known=known)
    providerconfig.set_model("ollama", "old-model", known=known)
    sessionconfig.set_default("quick", known=reviewprofiles.names())

    assert (
        init_module.cmd_init(
            _args(
                "--apply",
                "--default-profile",
                "thorough",
                "--enable-provider",
                "ollama",
                "--disable-provider",
                "codex",
                "--ollama-model",
                "qwen3:8b",
            )
        )
        == 0
    )

    assert sessionconfig.load().default_profile == "thorough"
    policy = providerconfig.load(known)
    assert policy.setting("ollama") == providerconfig.ProviderSetting(True, "qwen3:8b")
    assert policy.setting("codex") == providerconfig.ProviderSetting(False, None)
    assert policy.setting("opencode") == providerconfig.ProviderSetting(False, "gpt-5.6-sol")
    output = capsys.readouterr().err
    assert "changed:" in output
    assert "first review: afriend run <artifact>" in output
    assert "external tools remain denied" in output


def test_guided_apply_also_generates_the_normal_roster(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    registry = init_module.load_adapters(ADAPTER_DIR)
    rows = {
        "codex": readiness.FriendReadiness(
            "codex", readiness.ReadinessState.READY, "available", "/bin/codex", None
        )
    }
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: rows)

    assert (
        init_module.cmd_init(
            _args("--apply", "--default-profile", "balanced", "--out", str(target))
        )
        == 0
    )

    assert target.exists()
    assert 'cli = "codex"' in target.read_text(encoding="utf-8")
    output = capsys.readouterr().err
    assert str(target) in output
    assert str(sessionconfig.config_path()) in output
    assert set(rows) <= set(registry)


def test_the_roster_tells_the_operator_which_friends_the_os_confines(tmp_path, monkeypatch):
    """agy is sandboxed and the roster never said so.

    The note keyed on `is_readonly`, which agy declares true; the predicate
    dispatch decides with is `needs_os_confinement`, true for agy as well.
    So the one friend in the shipped set whose confinement changed in 0.10.1
    was the one friend the guided roster stayed silent about -- and the note
    it would have printed says "no read-only mode", which agy has.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    rows = {
        "agy": readiness.FriendReadiness(
            "agy", readiness.ReadinessState.READY, "available", "/bin/agy", None
        )
    }
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: rows)
    # A mechanism must exist for the note to promise confinement; Windows has none.
    monkeypatch.setattr(init_module.sandbox, "detect", lambda: init_module.sandbox.BWRAP)

    init_module.cmd_init(_args("--apply", "--default-profile", "balanced", "--out", str(target)))

    written = target.read_text(encoding="utf-8")
    note = next((line for line in written.splitlines() if "agy: " in line), None)

    assert note is not None, "agy got no confinement note at all"
    assert "OS confinement" in note
    # Two things the old note's wording asserts that are false for agy: it
    # HAS a read-only mode, and its entry above is written at repo scope.
    assert "no read-only mode" not in note
    assert "doc scope" not in note


def test_guided_apply_refuses_an_existing_roster_before_config_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    target.write_text("# do not replace\n", encoding="utf-8")

    with pytest.raises(UsageError, match="--force"):
        init_module.cmd_init(
            _args("--apply", "--default-profile", "balanced", "--out", str(target))
        )

    assert target.read_text(encoding="utf-8") == "# do not replace\n"
    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()


def test_guided_apply_does_not_persist_settings_when_no_roster_can_be_generated(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: {})

    with pytest.raises(NoFriendsError):
        init_module.cmd_init(
            _args("--apply", "--default-profile", "balanced", "--out", str(target))
        )

    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()
    assert not target.exists()


def test_guided_apply_stages_a_roster_against_requested_provider_enablement(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    known = _known()
    providerconfig.set_enabled("codex", False, known=known)

    def only_enabled_codex(_registry, policy, **_kwargs):
        if not policy.setting("codex").enabled:
            return {}
        return {
            "codex": readiness.FriendReadiness(
                "codex", readiness.ReadinessState.READY, "available", "/bin/codex", None
            )
        }

    monkeypatch.setattr(init_module, "assess_all", only_enabled_codex)

    assert (
        init_module.cmd_init(_args("--apply", "--enable-provider", "codex", "--out", str(target)))
        == 0
    )

    assert 'cli = "codex"' in target.read_text(encoding="utf-8")
    assert providerconfig.load(known).setting("codex").enabled is True


def test_guided_apply_force_replaces_the_existing_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    target.write_text("# replace me\n", encoding="utf-8")
    rows = {
        "codex": readiness.FriendReadiness(
            "codex", readiness.ReadinessState.READY, "available", "/bin/codex", None
        )
    }
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: rows)

    assert init_module.cmd_init(_args("--apply", "--force", "--out", str(target))) == 0

    assert target.read_text(encoding="utf-8") != "# replace me\n"


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        (("--apply",), "requires --guided"),
        (("--default-profile", "unknown"), "default profile.*one of"),
        (("--enable-provider", "unknown"), "provider.*one of"),
        (("--enable-provider", "codex", "--disable-provider", "codex"), "both enable and disable"),
        (("--ollama-model", "qwen3:8b"), "requires --enable-provider ollama"),
        (("--enable-provider", "ollama", "--ollama-model", ""), "model"),
        (
            ("--disable-provider", "ollama", "--ollama-model", "qwen3:8b"),
            "requires --enable-provider ollama",
        ),
    ],
)
def test_guided_setup_rejects_invalid_combinations_before_writes(
    tmp_path, monkeypatch, argv, match
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    parser = build_parser()
    args = (
        parser.parse_args(["init", *argv])
        if argv == ("--apply",)
        else parser.parse_args(["init", "--guided", *argv])
    )

    with pytest.raises(UsageError, match=match):
        init_module.cmd_init(args)

    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()


def test_guided_apply_requires_explicit_changes_before_creating_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: _ready_codex())

    assert init_module.cmd_init(_args("--apply")) == 0

    assert not sessionconfig.config_path().exists()
    assert not providerconfig.config_path().exists()


def test_the_roster_does_not_claim_confinement_on_a_host_that_has_none(tmp_path, monkeypatch):
    """The note asserted a mechanism the host does not have.

    `_render_roster` selected on the readiness state and read only
    `assessed.model`, discarding the qualification the row now carries. So on
    a Linux box without bubblewrap it wrote agy into the roster and told the
    operator agy "runs under OS confinement" -- describing a mechanism that
    is absent and a run dispatch will refuse.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    rows = {
        "agy": readiness.FriendReadiness(
            "agy", readiness.ReadinessState.READY, "available", "/bin/agy", None
        )
    }
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(init_module.sandbox, "detect", lambda *_a, **_k: None)

    init_module.cmd_init(_args("--apply", "--default-profile", "balanced", "--out", str(target)))

    note = next(
        (line for line in target.read_text(encoding="utf-8").splitlines() if "agy: " in line),
        None,
    )

    assert note is not None, "agy got no confinement note at all"
    assert "runs under OS confinement" not in note
    assert "no OS sandbox" in note
    assert "--allow-unsandboxed-friend" in note


def test_the_roster_note_states_the_scope_without_calling_it_a_limit(tmp_path, monkeypatch):
    """`repo` is the WIDER of the two scopes -- a git worktree of the code
    under review, against a doc-only directory -- so "limited to repo scope"
    reassures the operator with the larger of the two access grants."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    target = tmp_path / "roster.toml"
    rows = {
        "agy": readiness.FriendReadiness(
            "agy", readiness.ReadinessState.READY, "available", "/bin/agy", None
        )
    }
    monkeypatch.setattr(init_module, "assess_all", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(init_module.sandbox, "detect", lambda *_a, **_k: "bwrap")

    init_module.cmd_init(_args("--apply", "--default-profile", "balanced", "--out", str(target)))

    note = next(
        (line for line in target.read_text(encoding="utf-8").splitlines() if "agy: " in line),
        None,
    )

    assert note is not None
    assert "limited to repo scope" not in note
    assert "runs at repo scope" in note


def test_every_guided_only_flag_is_refused_without_guided_including_off_switches():
    """The off-switches are the whole point.

    The guard read `getattr(args, dest) not in (None, False, (), [])`, which
    is right for a `store_true` (default `False`) and for a collection
    (default `[]`), but wrong for the two `store_const` pairs whose
    off-switch carries `const=False` over a `None` default. For those,
    `False` is "the user explicitly asked for off" -- so
    `afriend init --disable-review-context` wrote a roster, printed success
    and exited 0 with the request discarded, while its sibling
    `--enable-review-context` was correctly refused. A guard that accepts
    exactly the half of each pair that turns something off is the defect
    this test exists to keep closed.
    """
    parser = build_parser()
    for flag in (
        "--enable-review-context",
        "--disable-review-context",
        "--review-context-automatic-combine",
        "--no-review-context-automatic-combine",
        "--review-context-sources=current-task",
        "--review-context-ambiguity=refuse",
        "--apply",
        "--json",
        "--default-profile=balanced",
        "--enable-provider=codex",
        "--disable-provider=codex",
        "--ollama-model=qwen3:8b",
    ):
        args = parser.parse_args(["init", flag])
        with pytest.raises(UsageError, match="--guided"):
            init_module.cmd_init(args)


def test_the_tri_state_set_is_exactly_what_the_parser_declares_as_tri_state():
    """Keep the hand-written set from drifting behind the parser.

    `_TRI_STATE_GUIDED_ONLY` names the dests where `False` means supplied.
    A new `store_const` off-switch added to `init` without being listed here
    would silently reintroduce the dropped-flag bug, and no other test would
    notice, so derive the truth from the parser's own actions instead of
    trusting the literal.
    """
    parser = build_parser()
    init_parser = parser._subparsers._group_actions[0].choices["init"]  # type: ignore[union-attr]

    guided_only_dests = {dest for dest, _flag in init_module._GUIDED_ONLY_FLAGS}
    tri_state = {
        action.dest
        for action in init_parser._actions
        if action.dest in guided_only_dests and action.const is False and action.default is None
    }

    assert tri_state == set(init_module._TRI_STATE_GUIDED_ONLY), (
        "a guided-only store_const off-switch is not listed as tri-state; "
        "its False would be read as 'not supplied' and the flag dropped"
    )
