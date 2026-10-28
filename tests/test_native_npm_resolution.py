"""Windows npm shims must not corrupt inline JSON on a second shell parse."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from afriend import execresolve


def layout(tmp_path, command="claude", package="@anthropic-ai/claude-code", *, custom=False):
    prefix = tmp_path / "npm"
    prefix.mkdir()
    shim = prefix / f"{command}.CMD"
    relative = Path("node_modules") / package / "bin" / f"{command}.exe"
    native = prefix / relative
    native.parent.mkdir(parents=True)
    native.write_bytes(b"MZ-native-test-placeholder")
    target = str(relative).replace("/", "\\")
    header = "@ECHO off\nGOTO start\n:find_dp0\nSET dp0=%~dp0\nEXIT /b\n:start\nSETLOCAL\nCALL :find_dp0\n"
    shim.write_text("@echo custom launcher\n" if custom else header + f'"%dp0%\\{target}"   %*\n')
    return prefix, shim, native


def windows(monkeypatch, prefix, found):
    monkeypatch.setattr(execresolve, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(execresolve.shutil, "which", lambda _name: str(found))
    monkeypatch.setenv("PATH", str(prefix))


@pytest.mark.parametrize(
    "command,package", [("claude", "@anthropic-ai/claude-code"), ("opencode", "@opencode/cli")]
)
def test_recognized_native_npm_shim_resolves_directly(monkeypatch, tmp_path, command, package):
    prefix, shim, native = layout(tmp_path, command, package)
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which(command) == str(native.resolve())


def test_custom_launcher_keeps_its_own_selection(monkeypatch, tmp_path):
    prefix, shim, _ = layout(tmp_path, custom=True)
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which("claude") == str(shim)


def test_missing_native_target_does_not_invent_a_command(monkeypatch, tmp_path):
    prefix, shim, native = layout(tmp_path)
    native.unlink()
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which("claude") == str(shim)


def test_checkout_executable_is_rejected_before_native_unwrapping(monkeypatch, tmp_path):
    _prefix, shim, _ = layout(tmp_path)
    other = tmp_path / "trusted-path"
    other.mkdir()
    windows(monkeypatch, other, shim)
    assert execresolve.safe_which("claude") is None


def test_posix_resolution_does_not_unwrap_windows_shims(monkeypatch, tmp_path):
    prefix, shim, _ = layout(tmp_path)
    windows(monkeypatch, prefix, shim)
    monkeypatch.setattr(execresolve, "sys", SimpleNamespace(platform="linux"))
    assert execresolve.safe_which("claude") == str(shim)


def test_unrecognized_package_keeps_its_shim(monkeypatch, tmp_path):
    prefix, shim, _ = layout(tmp_path, "custom", "@example/custom")
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which("custom") == str(shim)


def test_native_lookup_uses_the_real_shim_directory(monkeypatch, tmp_path):
    prefix, shim, native = layout(tmp_path)
    alias = tmp_path / "alias.CMD"
    try:
        alias.symlink_to(shim)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    windows(monkeypatch, prefix, alias)
    assert execresolve.safe_which("claude") == str(native.resolve())


@pytest.mark.parametrize("customization", ["profile", "model"])
def test_custom_forwarding_wrapper_is_not_bypassed(monkeypatch, tmp_path, customization):
    prefix, shim, _ = layout(tmp_path)
    content = shim.read_text()
    if customization == "profile":
        content = content.replace(
            "CALL :find_dp0\n", "CALL :find_dp0\nSET CLAUDE_CONFIG_DIR=custom\n"
        )
    else:
        content = content.replace("%*\n", "--model custom-model %*\n")
    shim.write_text(content)
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which("claude") == str(shim)


def test_custom_commands_beyond_the_inspection_bound_are_preserved(monkeypatch, tmp_path):
    prefix, shim, _ = layout(tmp_path)
    shim.write_text(shim.read_text() + "\n" * 16384 + "echo custom post-launch hook\n")
    windows(monkeypatch, prefix, shim)
    assert execresolve.safe_which("claude") == str(shim)
