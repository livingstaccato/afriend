"""Pi's configured state directory must match its confined credential grants."""

import json
from pathlib import Path
import sys

import pytest

from afriend import dispatch, sandbox
from afriend.adapters import FriendSpec, load_adapters
from afriend.normalize import NormalizeResult
from afriend.paths import ADAPTER_DIR
from afriend.spawn import SpawnResult


def _grant(path: Path) -> str:
    return f"(subpath {json.dumps(str(path), ensure_ascii=False)})"


@pytest.mark.parametrize(
    "redirect",
    [
        "absolute",
        "relative",
        "tilde",
        "tilde-double-slash",
        "home-only",
        "uri",
        "literal-dollar",
        "directory",
        "symlink-dir",
        "",
        None,
    ],
)
def test_pi_confines_credentials_at_the_effective_state_directory(monkeypatch, tmp_path, redirect):
    """A redirected Pi must read its own credentials without gaining settings/history
    or retaining access to the default profile's credentials.
    """
    home = tmp_path / "home"
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    if redirect == "absolute":
        value, expected = str(home / "custom"), home / "custom"
    elif redirect == "relative":
        value, expected = "../state", tmp_path / "state"
    elif redirect == "tilde":
        value, expected = "~/custom", home / "custom"
    elif redirect == "tilde-double-slash":
        value, expected = "~//custom", home / "custom"
    elif redirect == "home-only":
        value, expected = "~", home
    elif redirect == "uri":
        expected = home / "custom state"
        value = expected.as_uri()
    elif redirect in {"directory", "symlink-dir"}:
        value, expected = str(home / "custom"), home / "custom"
        expected.mkdir(parents=True)
        for filename in ("auth.json", "models.json"):
            endpoint = expected / filename
            if redirect == "directory":
                endpoint.mkdir()
            else:
                target = tmp_path / filename
                target.mkdir()
                try:
                    endpoint.symlink_to(target, target_is_directory=True)
                except OSError:
                    pytest.skip("directory symlinks unavailable on this host")
    elif redirect == "literal-dollar":
        monkeypatch.setenv("PI_TEST_STATE", "wrong-directory")
        value, expected = str(home / "$PI_TEST_STATE"), home / "$PI_TEST_STATE"
    else:
        value, expected = redirect, home / ".pi" / "agent"
    if value is None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    else:
        monkeypatch.setenv("PI_CODING_AGENT_DIR", value)
    monkeypatch.setattr(dispatch.execresolve, "safe_which", lambda _name: sys.executable)
    monkeypatch.setattr(sandbox, "detect", lambda: sandbox.SANDBOX_EXEC)

    def complete(argv, *_args, **_kwargs):
        if redirect == "relative":
            assert _kwargs["env"]["PI_CODING_AGENT_DIR"] == str(expected)
        return SpawnResult(
            argv,
            0,
            "",
            "",
            0,
            False,
            NormalizeResult({"no_findings": True}, [], True),
            None,
            False,
        )

    # The external process is the only stub: dispatch, policy construction and
    # serialized Seatbelt grants all run normally on every platform.
    monkeypatch.setattr(dispatch, "run_process", complete)
    prompt = tmp_path / "review.prompt"
    prompt.write_text("Review this contract.")
    spec = FriendSpec("pi-ops-0", "pi", "ops", None, None, "doc", 5)
    dispatch._dispatch(spec, workdir, load_adapters(ADAPTER_DIR), None, prompt, tmp_path / "s.json")
    profile = prompt.with_suffix(".sandbox").read_text()
    if redirect == "relative":
        assert "/../" not in profile and "\\\\..\\\\" not in profile
    for filename in ("auth.json", "models.json"):
        credential_grant = _grant(expected / filename)
        if redirect in {"directory", "symlink-dir"}:
            assert credential_grant not in profile
            assert _grant(tmp_path / filename) not in profile
        else:
            assert credential_grant in profile
        if redirect:
            assert _grant(home / ".pi" / "agent" / filename) not in profile
    assert _grant(expected) not in profile
    assert _grant(expected / "settings.json") not in profile
    assert _grant(expected / "sessions") not in profile
