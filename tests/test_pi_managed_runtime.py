"""Managed Pi's launcher must retain its interpreter after private state setup."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from afriend import dispatch, managedruntime, sandbox
from afriend.adapters import FriendSpec, load_adapters
from afriend.normalize import NormalizeResult
from afriend.paths import ADAPTER_DIR
from afriend.spawn import SpawnResult


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.mark.posix_only(reason="executes the installed POSIX Pi launcher")
@pytest.mark.parametrize("data_home", [None, "custom-data", "literal-$DATA"])
def test_managed_pi_node_survives_private_xdg(monkeypatch, tmp_path, data_home):
    _run_launcher(monkeypatch, tmp_path, data_home=data_home, managed=True)


@pytest.mark.posix_only(reason="executes the installed POSIX Pi launcher")
def test_pi_system_node_is_unchanged(monkeypatch, tmp_path):
    _run_launcher(monkeypatch, tmp_path, managed=False)


@pytest.mark.posix_only(reason="executes the installed POSIX Pi launcher")
def test_pi_node_uses_absolute_filtered_child_path(monkeypatch, tmp_path):
    _run_launcher(monkeypatch, tmp_path, managed=False, hostile_path=True)


@pytest.mark.posix_only(reason="executes a POSIX npm-style Pi entrypoint")
def test_npm_pi_ignores_an_unrelated_managed_node(monkeypatch, tmp_path):
    _run_launcher(monkeypatch, tmp_path, managed=False, other_managed_install=True)


@pytest.mark.posix_only(reason="managed POSIX Node runtime discovery")
def test_pi_node_selection_uses_child_environment_and_follows_current_symlink(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path / "wrong-home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "wrong-data"))
    actual = tmp_path / "child-data/pi-node/releases/test-version"
    _executable(actual / "bin/node", "#!/bin/sh\nexit 0\n")
    current = tmp_path / "child-data/pi-node/current"
    current.symlink_to(actual, target_is_directory=True)
    env = {"HOME": str(tmp_path / "child-home"), "XDG_DATA_HOME": "child-data", "PATH": ""}
    launcher = Path(__file__).parent / "fixtures/pi/managed-launcher.sh"
    reads = managedruntime.pi_node_reads(env, tmp_path, str(launcher))
    assert env["PATH"] == str(current / "bin")
    policy = sandbox.policy_for(tmp_path / "work", None, (), runtime_read=reads)
    assert actual in policy.read_paths
    assert actual / "bin/node" in policy.read_paths
    assert actual.parent not in policy.read_paths
    assert tmp_path / "child-data" not in policy.read_paths
    assert not policy.write_paths


@pytest.mark.posix_only(reason="managed POSIX Node runtime discovery")
def test_missing_pi_node_does_not_grant_or_use_relative_path(tmp_path):
    env = {"HOME": str(tmp_path / "home"), "PATH": ".:relative:"}
    _executable(tmp_path / "node", "#!/bin/sh\nexit 0\n")
    assert managedruntime.pi_node_reads(env, tmp_path) == ()
    process = subprocess.run(["/usr/bin/env", "node"], cwd=tmp_path, env=env, capture_output=True)
    assert process.returncode != 0


@pytest.mark.posix_only(reason="POSIX execvp supplies a default when PATH is absent")
def test_absent_pi_path_uses_safe_system_default(monkeypatch, tmp_path):
    tools = tmp_path / "system-bin"
    node = tools / "node"
    _executable(node, "#!/bin/sh\nprintf 'DEFAULT_NODE\\n'\n")
    monkeypatch.setattr(managedruntime.os, "defpath", str(tools))
    env = {"HOME": str(tmp_path / "home")}
    reads = managedruntime.pi_node_reads(env, tmp_path)
    process = subprocess.run(["/usr/bin/env", "node"], cwd=tmp_path, env=env, capture_output=True)
    assert process.returncode == 0, process.stderr
    assert process.stdout == b"DEFAULT_NODE\n"
    policy = sandbox.policy_for(tmp_path / "work", None, (), runtime_read=reads)
    assert node in policy.read_paths
    assert tools not in policy.read_paths


@pytest.mark.posix_only(reason="executes a POSIX system Node stand-in")
@pytest.mark.parametrize("entrypoint", ["absent", "directory", "symlink", "no-state"])
def test_pi_launcher_discovery_failure_preserves_system_node(tmp_path, entrypoint):
    tools = tmp_path / "system-bin"
    node = tools / "node"
    _executable(node, "#!/bin/sh\nprintf 'SYSTEM_NODE\\n'\n")
    launcher = tmp_path / "pi"
    if entrypoint == "directory":
        launcher.mkdir()
    elif entrypoint == "symlink":
        launcher.symlink_to(Path(__file__).parent / "fixtures/pi/managed-launcher.sh")
    env = {"PATH": str(tools)}
    if entrypoint != "no-state":
        env["HOME"] = str(tmp_path / "home")
    # No HOME/XDG_DATA_HOME is also valid: interpreter discovery must not
    # invent a private state path or discard an available system Node.
    assert managedruntime.pi_node_reads(env, tmp_path, str(launcher)) == (str(node),)
    process = subprocess.run(["/usr/bin/env", "node"], env=env, capture_output=True)
    assert process.returncode == 0
    assert process.stdout == b"SYSTEM_NODE\n"


def test_non_posix_pi_environment_is_left_unchanged(monkeypatch, tmp_path):
    # Exercise the portable guard, without claiming Windows native execution.
    monkeypatch.setattr(managedruntime, "os", SimpleNamespace(name="nt"))
    env = {"PATH": "C:\\tools", "HOME": "C:\\Users\\reviewer"}
    assert managedruntime.pi_node_reads(env, tmp_path) == ()
    assert env == {"PATH": "C:\\tools", "HOME": "C:\\Users\\reviewer"}


@pytest.mark.posix_only(reason="POSIX executable FIFO must not block launcher inspection")
def test_executable_fifo_cannot_stall_pi_dispatch_setup(tmp_path):
    fifo = tmp_path / "pi"
    os.mkfifo(fifo, 0o700)
    script = (
        "import sys; from afriend import execresolve, managedruntime; "
        "assert execresolve.safe_which('pi') == sys.argv[1]; "
        "assert managedruntime.pi_node_reads("
        "{'PATH': sys.argv[2], 'HOME': sys.argv[2]}, "
        "__import__('pathlib').Path(sys.argv[2]), sys.argv[1]) == ()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(fifo), str(tmp_path)],
        env=dict(os.environ, PATH=str(tmp_path)),
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert result.returncode == 0, result.stderr


def _run_launcher(
    monkeypatch,
    tmp_path,
    *,
    data_home=None,
    managed,
    hostile_path=False,
    other_managed_install=False,
):
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    if data_home is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        data = home / ".local/share"
    else:
        data = tmp_path / data_home
        monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("DATA", "wrong-expanded-path")
    agent = home / ".pi/agent"
    launcher = agent / "bin/pi"
    _executable(launcher, (Path(__file__).parent / "fixtures/pi/managed-launcher.sh").read_text())
    version = agent / "install/current-version"
    version.parent.mkdir(parents=True)
    version.write_text("test-version\n")
    _executable(
        agent / "install/releases/test-version/node_modules/.bin/pi", "#!/usr/bin/env node\n"
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    runtime = data / "pi-node/current"
    node = runtime / "bin/node" if managed else tools / "node"
    _executable(node, "#!/bin/sh\nprintf '{\"no_findings\":true}\\n'\n")
    if other_managed_install:
        # A directly installed Pi relies on PATH, not the managed launcher's
        # private Node selection. A stale managed runtime must not replace it.
        _executable(launcher, "#!/usr/bin/env node\n")
        _executable(runtime / "bin/node", "#!/bin/sh\nexit 42\n")
    path = str(tools)
    if hostile_path:
        _executable(work / "node", "#!/bin/sh\nprintf 'HOSTILE_NODE\\n'\n")
        path = f".:relative:{tools}"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setattr(dispatch.execresolve, "safe_which", lambda _name: str(launcher))
    monkeypatch.setattr(sandbox, "detect", lambda: sandbox.SANDBOX_EXEC)
    captured = {}

    def wrap(argv, mechanism, policy, profile):
        captured["policy"] = policy
        return argv

    def execute(argv, *_args, **kwargs):
        env = kwargs["env"]
        assert env["XDG_DATA_HOME"] == str(tmp_path / "work.private/state")
        process = subprocess.run([str(launcher)], cwd=work, env=env, text=True, capture_output=True)
        assert process.returncode == 0, process.stderr
        assert process.stdout == '{"no_findings":true}\n'
        if not managed and not hostile_path:
            assert env["PATH"] == str(tools)
        return SpawnResult(
            argv,
            0,
            process.stdout,
            process.stderr,
            0,
            False,
            NormalizeResult({"no_findings": True}, [], True),
            None,
            False,
        )

    monkeypatch.setattr(sandbox, "wrap", wrap)
    monkeypatch.setattr(dispatch, "run_process", execute)
    prompt = tmp_path / "review.prompt"
    prompt.write_text("Review this contract.")
    spec = FriendSpec("pi-ops-0", "pi", "ops", None, None, "doc", 5)
    dispatch._dispatch(spec, work, load_adapters(ADAPTER_DIR), None, prompt, tmp_path / "s.json")
    policy = captured["policy"]
    assert node.resolve() in policy.read_paths
    if other_managed_install:
        assert runtime not in policy.read_paths
        assert runtime / "bin/node" not in policy.read_paths
    for broad in (home, home / ".local", data, data / "pi-node", agent):
        assert broad not in policy.read_paths
        assert broad not in policy.write_paths
    assert not any(path in (runtime, node) for path in policy.write_paths)
    assert agent / "settings.json" not in policy.read_paths
    assert agent / "sessions" not in policy.read_paths
