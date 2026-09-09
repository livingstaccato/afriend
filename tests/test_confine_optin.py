"""OS confinement for a CLI that already has a read-only mode (§12.2).

A read-only flag stops a friend WRITING and says nothing about what it may
READ. Measured against the real codex on 2026-08-28: under its own
`--sandbox read-only` and nothing else, asked to list `~/.ssh`, it listed the
directory. Under this runner's sandbox the same request came back "the
filesystem sandbox denied access (Operation not permitted)".

The opt-in is per adapter rather than blanket because confinement breaks a
CLI whose credentials the sandbox cannot reach: claude keeps its own in the
macOS Keychain and reports "Not logged in" under any profile that does not
grant `~/Library/Keychains` -- and granting that would hand a friend every
credential the operator has, which is worse than the gap it closes. claude's
own `--tools Read,Grep,Glob` allowlist was measured and does hold, so only
the read gap remains there.

agy was left out on the same reasoning until its flags were measured, and
none of them restricted anything: it wrote files and read an absolute path
outside its working directory. It opts in now, with `~/.gemini` granted read
and write so its token refresh still succeeds -- withholding that is what
would provoke the re-authentication that cost a login before.
"""

from dataclasses import replace
from pathlib import Path

from afriend.adapters import load_adapters
from afriend.paths import ADAPTER_DIR


def _registry():
    return load_adapters(ADAPTER_DIR)


def test_codex_opts_in_and_declares_what_it_needs():
    codex = _registry()["codex"]
    assert codex.sandbox_confine is True
    # It writes session state and sqlite files under CODEX_HOME on every run
    # and exits if it cannot, so read alone is not enough.
    assert any("codex" in p for p in codex.sandbox_read)
    assert any("codex" in p for p in codex.sandbox_write)


def test_codex_confined_startup_reads_only_its_state_and_global_skill_root():
    codex = _registry()["codex"]

    assert "~/.codex" in codex.sandbox_read
    assert "~/.agents/skills" in codex.sandbox_read
    assert all(path != "~/.agents" for path in codex.sandbox_read)
    assert all(path != "~" for path in codex.sandbox_read)


def test_codex_uses_outer_readonly_confinement_not_a_nested_sandbox():
    codex = _registry()["codex"]

    assert codex.is_readonly is True
    assert codex.is_self_confining is False
    assert codex.sandbox_readonly_workdir is True
    assert codex.readonly_argv == ["--sandbox", "danger-full-access"]


def test_codex_denial_argv_disables_builtin_remote_tools_too():
    codex = _registry()["codex"]

    for feature in (
        "apps",
        "plugins",
        "browser_use",
        "browser_use_external",
        "computer_use",
        "in_app_browser",
        "standalone_web_search",
    ):
        assert ("--disable", feature) in zip(
            codex.deny_external_tools_argv,
            codex.deny_external_tools_argv[1:],
            strict=False,
        )


def test_codex_dispatch_makes_the_outer_workdir_readonly(monkeypatch, tmp_path):
    from afriend import dispatch, sandbox
    from afriend.adapters import FriendSpec

    captured = []
    codex = replace(_registry()["codex"], binary="true", base_argv=[], schema_flag="")
    spec = FriendSpec("codex-ops-0", "codex", "ops", None, None, "repo", 5)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("probe")

    monkeypatch.setattr(sandbox, "detect", lambda: sandbox.BWRAP)

    def capture_wrap(argv, _mechanism, policy, _profile):
        captured.append(policy)
        return argv

    monkeypatch.setattr(sandbox, "wrap", capture_wrap)
    _spec, capability, outcome, _policy = dispatch._dispatch(
        spec, tmp_path, {"codex": codex}, None, prompt, tmp_path / "schema.json"
    )

    assert captured and captured[0].workdir_writable is False
    assert capability.readonly is True
    assert outcome.os_confined is True


def test_codex_declares_its_measured_sandbox_access_failure_marker():
    codex = _registry()["codex"]

    assert codex.sandbox_access_failure_stderr == (
        "codex_skills_extension::loader::host: failed to scan skill path",
    )


def test_claude_does_not_opt_in():
    """Not an oversight. Confining claude requires granting the Keychain,
    which is a worse outcome than the gap -- see this module's docstring."""
    assert _registry()["claude"].sandbox_confine is False


def test_agy_opts_in_because_none_of_its_own_flags_restrict_anything():
    """Measured against installed agy 1.1.22, with the reviewer agent staged
    exactly as dispatch stages it: it wrote a file (relocated by `--sandbox`
    into ~/.gemini/antigravity-cli/scratch, not blocked) and read an absolute
    path outside its working directory. `tools: []` in the agent did not stop
    tool use, and `--mode plan` is inert -- agy itself warns that
    `--disable-slash-commands`, in the same list, disables it.

    So the non-empty `readonly_argv` that made this adapter "self-confining"
    by inference bought real trust for nothing, and it was the one shipped
    adapter running unconfined.
    """
    agy = _registry()["agy"]

    assert agy.sandbox_confine is True
    assert agy.is_self_confining is False
    assert "--mode" not in agy.readonly_argv


def test_agy_keeps_its_own_state_directory_reachable():
    """The failure mode this guards is specific: a confined agy that cannot
    refresh its OAuth token re-authenticates, and that has cost a login."""
    agy = _registry()["agy"]

    assert "~/.gemini" in agy.sandbox_read
    assert "~/.gemini" in agy.sandbox_write
    assert all(path != "~" for path in agy.sandbox_read)


def test_claude_still_confines_itself_because_its_allowlist_holds():
    """The distinction the derivation could not make: claude and agy had the
    same shape -- a non-empty readonly_argv and nothing explicit -- but
    claude's is a tool allowlist on the CLI's own flag, and it works."""
    claude = _registry()["claude"]

    assert claude.is_self_confining is True
    assert claude.sandbox_confine is False
    assert claude.readonly_argv == ["--tools", "Read,Grep,Glob"]


def test_opting_in_is_off_by_default_for_a_new_adapter():
    """An adapter that says nothing about confinement must not be silently
    confined: the whole point of the opt-in is that someone verified that
    CLI actually runs under a sandbox."""
    import tomllib

    from afriend.adapters import load_adapters

    directory = Path(__file__).parent / "_fresh_adapter"
    directory.mkdir(exist_ok=True)
    (directory / "brandnew.toml").write_text(
        'name = "brandnew"\nbinary = "brandnew"\nprompt_mode = "stdin"\n'
    )
    try:
        fresh = load_adapters(directory)["brandnew"]
        assert fresh.sandbox_confine is False
        assert tomllib is not None
    finally:
        (directory / "brandnew.toml").unlink()
        directory.rmdir()


def test_a_cli_with_no_readonly_mode_is_still_confined_without_opting_in():
    """opencode must keep being confined on the old grounds -- it enforces
    nothing itself -- rather than needing the new flag."""
    opencode = _registry()["opencode"]
    assert not opencode.readonly_argv
    assert opencode.sandbox_confine is False


def _adapter_toml(tmp_path, body: str):
    from afriend.adapters import load_adapters

    (tmp_path / "probe.toml").write_text(
        'name = "probe"\nbinary = "probe"\nprompt_mode = "stdin"\n' + body
    )
    return load_adapters(tmp_path)["probe"]


def test_declaring_restriction_flags_without_saying_whether_they_work_is_refused(tmp_path):
    """The defect underneath the agy hole, closed at the source.

    `is_readonly` and `is_self_confining` used to fall back to
    `bool(readonly_argv)` -- the PRESENCE of flags, never their effect. agy
    declared four that restricted nothing and was handed a real confinement
    exemption for them. Nothing in the adapter format asked whether anyone had
    checked, so nothing could tell agy's dead flags from claude's working
    allowlist.
    """
    import pytest

    from afriend.errors import UsageError

    with pytest.raises(UsageError, match="self_confines"):
        _adapter_toml(tmp_path, 'readonly_argv = ["--pretend-read-only"]\n')


def test_an_adapter_with_no_restriction_flags_needs_no_declaration(tmp_path):
    """Claiming nothing is still allowed, and still means confined: opencode
    and ollama declare no readonly_argv and get OS confinement."""
    probe = _adapter_toml(tmp_path, "")

    assert probe.is_readonly is False
    assert probe.is_self_confining is False


def test_flags_declared_as_verified_are_taken_at_their_word(tmp_path):
    probe = _adapter_toml(
        tmp_path,
        'readonly_argv = ["--tools", "read-only"]\nreadonly = true\nself_confines = true\n',
    )

    assert probe.is_readonly is True
    assert probe.is_self_confining is True


def test_flags_declared_as_not_confining_still_get_the_sandbox(tmp_path):
    """agy's shape: the flags exist and are worth passing, but they do not
    confine, so the friend is OS-confined anyway."""
    probe = _adapter_toml(
        tmp_path,
        'readonly_argv = ["--sandbox"]\nreadonly = false\nself_confines = false\n',
    )

    assert probe.is_self_confining is False


def test_no_shipped_adapter_relies_on_the_inference():
    """The guard against reintroducing it: every adapter that declares
    restriction flags says explicitly whether they work."""
    for name, adapter in _registry().items():
        if adapter.readonly_argv:
            assert adapter.readonly is not None, name
            assert adapter.self_confines is not None, name
