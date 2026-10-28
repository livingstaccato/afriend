"""OpenCode dispatch environment, using a portable real child process.

The sandbox wrapper is substituted to inspect confinement setup on every
platform. These tests exercise environment delivery, not OS enforcement.
"""

import dataclasses
import json
import sys

import pytest

from afriend import dispatch, sandbox
from afriend.adapters import FriendSpec, load_adapters
from afriend.authority import AuthorityPolicy
from afriend.paths import ADAPTER_DIR


@pytest.mark.parametrize("confined", [False, True])
@pytest.mark.parametrize("explicit_config", [False, True])
def test_opencode_config_reaches_child_after_optional_private_env_redirect(
    monkeypatch, tmp_path, confined, explicit_config
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    xdg = home / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    custom_config = home / "custom-opencode"
    if explicit_config:
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(custom_config))
    else:
        monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sandbox, "detect", lambda: sandbox.BWRAP if confined else None)
    monkeypatch.setattr(sandbox, "wrap", lambda argv, *_args: argv)
    code = (
        "import json, os; print(json.dumps({"
        "'config': os.environ.get('OPENCODE_CONFIG_DIR'), "
        "'xdg': os.environ.get('XDG_CONFIG_HOME')}))"
    )
    adapter = dataclasses.replace(
        load_adapters(ADAPTER_DIR)["opencode"],
        binary=sys.executable,
        base_argv=("-c", code),
        envelope=None,
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Review the artifact.")
    spec = FriendSpec(
        name="opencode-test",
        cli="opencode",
        lens="general",
        model=None,
        effort=None,
        scope="repo",
        timeout=10,
    )
    _, _, outcome, _ = dispatch._dispatch(
        spec,
        workdir,
        {"opencode": adapter},
        None,
        prompt,
        tmp_path / "schema.json",
        allow_unsandboxed=True,
        authority_policy=AuthorityPolicy(("opencode",)),
    )
    assert outcome.exit_code == 0, outcome.stderr
    assert outcome.os_confined is confined
    observed = json.loads(outcome.stdout)
    expected = str(custom_config) if explicit_config else None
    if confined and not explicit_config:
        expected = str(home / ".config" / "opencode")
    assert observed["config"] == expected
    assert (observed["xdg"] != str(xdg)) is confined
