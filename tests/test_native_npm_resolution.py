"""Windows npm shims must not corrupt inline JSON on a second shell parse."""

import json
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


# npm cmd-shim's template for a Node-script bin, as `npm install -g
# @moonshot-ai/kimi-code` writes it on Windows.
NODE_SHIM = (
    "@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\n"
    'CALL :find_dp0\r\n\r\nIF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n'
    ') ELSE (\r\n  SET "_prog=node"\r\n  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@moonshot-ai\\kimi-code\\dist\\main.mjs" %*\r\n'
)


def node_layout(tmp_path, shim_text=NODE_SHIM, *, sibling_node=True, bin_entry="dist/main.mjs"):
    prefix = tmp_path / "npm"
    package = prefix / "node_modules" / "@moonshot-ai" / "kimi-code"
    (package / "dist").mkdir(parents=True)
    (package / "dist" / "main.mjs").write_text("// entry\n")
    (package / "package.json").write_text(json.dumps({"bin": {"kimi": bin_entry}}))
    shim = prefix / "kimi.CMD"
    shim.write_text(shim_text, newline="")
    node = prefix / "node.exe"
    if sibling_node:
        node.write_bytes(b"MZ-node-placeholder")
    return prefix, shim, node, package / "dist" / "main.mjs"


def test_a_node_script_shim_launches_node_directly(monkeypatch, tmp_path):
    """kimi's argv prompt must never take cmd.exe's second parse."""
    prefix, shim, node, script = node_layout(tmp_path)
    windows(monkeypatch, prefix, shim)
    assert execresolve.launch_prefix("kimi") == [str(node.resolve()), str(script.resolve())]


def test_without_a_sibling_node_the_path_node_is_used(monkeypatch, tmp_path):
    prefix, shim, _node, script = node_layout(tmp_path, sibling_node=False)
    windows(monkeypatch, prefix, shim)
    path_node = tmp_path / "nodejs" / "node.exe"
    real_safe_which = execresolve.safe_which
    monkeypatch.setattr(
        execresolve,
        "safe_which",
        lambda name: str(path_node) if name == "node" else real_safe_which(name),
    )
    assert execresolve.launch_prefix("kimi") == [str(path_node), str(script.resolve())]


@pytest.mark.parametrize(
    "shim_text",
    [
        "@echo custom launcher\r\n",
        NODE_SHIM.replace('main.mjs" %*', 'main.mjs" --yolo %*'),
        NODE_SHIM.replace('IF EXIST "%dp0%\\node.exe" (', "IF 1==1 ("),
    ],
    ids=["custom", "extra-arguments", "no-node-selection"],
)
def test_a_node_shim_that_is_not_the_npm_template_keeps_its_selection(
    monkeypatch, tmp_path, shim_text
):
    prefix, shim, _node, _script = node_layout(tmp_path, shim_text)
    windows(monkeypatch, prefix, shim)
    assert execresolve.launch_prefix("kimi") == [str(shim)]


def test_a_bin_entry_escaping_the_package_is_refused(monkeypatch, tmp_path):
    prefix, shim, _node, _script = node_layout(tmp_path, bin_entry="../../../evil.mjs")
    (prefix / "evil.mjs").write_text("// outside\n")
    windows(monkeypatch, prefix, shim)
    assert execresolve.launch_prefix("kimi") == [str(shim)]


def test_off_windows_the_launch_prefix_is_the_resolved_path(monkeypatch, tmp_path):
    _prefix, shim, _node, _script = node_layout(tmp_path)
    monkeypatch.setattr(execresolve, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(execresolve.shutil, "which", lambda _name: str(shim))
    assert execresolve.launch_prefix("kimi") == [str(shim)]


def test_an_argv_prompt_adapter_behind_a_batch_launcher_is_refused(monkeypatch, tmp_path):
    """If the shim cannot be unwrapped, kimi must not run through cmd.exe."""
    from afriend import adapters
    from afriend.authority import ExternalToolPolicy
    from afriend.errors import UsageError
    from afriend.paths import ADAPTER_DIR

    prefix, shim, _node, _script = node_layout(tmp_path, "@echo custom launcher\r\n")
    windows(monkeypatch, prefix, shim)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("line one\nline two & more")
    schema = tmp_path / "s.json"
    schema.write_text("{}")
    spec = adapters.FriendSpec("kimi-ops-0", "kimi", "ops", None, None, "doc", 30)
    kimi = adapters.load_adapters(ADAPTER_DIR)["kimi"]
    with pytest.raises(UsageError, match=r"cmd\.exe would re-parse"):
        adapters.build_argv(kimi, spec, prompt, schema, ExternalToolPolicy.ALLOW)
