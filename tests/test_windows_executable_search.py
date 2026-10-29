"""An authorized npm shim must not find its interpreter in the checkout."""

import dataclasses
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from afriend import childenv, execresolve, models, readiness
from afriend.adapters import load_adapters
from afriend.paths import ADAPTER_DIR


@pytest.mark.parametrize("parent_value", [None, "0", "1"])
def test_filtered_windows_environment_forces_safe_interpreter_search(monkeypatch, parent_value):
    monkeypatch.setattr(childenv, "sys", SimpleNamespace(platform="win32"), raising=False)
    source = {"PATH": ".;trusted"}
    if parent_value is not None:
        source["NODEFAULTCURRENTDIRECTORYINEXEPATH"] = parent_value
    result = childenv.build(operator_pass=("NoDefaultCurrentDirectoryInExePath",), environ=source)
    protection = {
        k: v for k, v in result.items() if k.upper() == "NODEFAULTCURRENTDIRECTORYINEXEPATH"
    }
    assert list(protection.values()) == ["1"]
    assert result["PATH"] == ".;trusted"


def test_windows_capability_probe_protects_inherited_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(childenv, "sys", SimpleNamespace(platform="win32"), raising=False)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    monkeypatch.setenv("PROBE_CUSTOM_SETTING", "preserved")
    adapter = load_adapters(ADAPTER_DIR)["pi"]
    captured = []

    def start(argv, **kwargs):
        captured.append(kwargs.get("env"))
        raise OSError("captured before execution")

    monkeypatch.setattr(readiness.subprocess, "Popen", start)
    readiness.probe_deny_argv(adapter, str(tmp_path / "pi.cmd"))
    assert captured[0] is not None
    assert captured[0]["NoDefaultCurrentDirectoryInExePath"] == "1"
    assert captured[0]["PROBE_CUSTOM_SETTING"] == "preserved"


@pytest.fixture
def native_node_shim(monkeypatch, tmp_path):
    node = execresolve.safe_which("node")
    if node is None or Path(node).suffix.lower() != ".exe":
        if os.environ.get("CI"):
            pytest.fail("Windows executable-search regression requires Node.js on PATH")
        pytest.skip("native regression requires Node.js on PATH")
    node = Path(node).resolve()
    prefix = tmp_path / "npm prefix & tools"
    checkout = tmp_path / "checkout"
    prefix.mkdir()
    checkout.mkdir()
    hostile_node = checkout / "node.exe"
    shutil.copy2(node, hostile_node)
    marker = checkout / "interpreter-ran.txt"
    script = prefix / "cli.js"
    # The copied runtime is a harmless stand-in for an attacker-controlled PE.
    # Its process.execPath proves which executable cmd.exe actually selected.
    script.write_text(
        'const fs = require("node:fs");\n'
        'const path = require("node:path");\n'
        "const hostile = path.dirname(process.execPath).toLowerCase() === process.cwd().toLowerCase();\n"
        'if (hostile) fs.writeFileSync("interpreter-ran.txt", process.execPath);\n'
        'const custom = process.env.SHIM_CUSTOM === "yes" && process.argv.includes("two words");\n'
        'console.log(hostile ? "hostile/runtime" : custom ? "trusted/custom" : "trusted/runtime");\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("PATH", os.pathsep.join((str(prefix), str(node.parent), os.environ["PATH"])))
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)

    def make(command="pi", *, custom=False):
        shim = prefix / f"{command}.cmd"
        # npm/cmd-shim's Node forwarding template, including endLocal, so the
        # test exercises its real shell parsing rather than a mock resolver.
        shim.write_text(
            "@ECHO off\n"
            + ('SET "SHIM_CUSTOM=yes"\n' if custom else "")
            + "GOTO start\n:find_dp0\nSET dp0=%~dp0\nEXIT /b\n"
            ":start\nSETLOCAL\nCALL :find_dp0\n" + '\nIF EXIST "%dp0%\\node.exe" (\n'
            '  SET "_prog=%dp0%\\node.exe"\n'
            ') ELSE (\n  SET "_prog=node"\n)\n\n'
            "endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "
            'set PATHEXT=%PATHEXT:;.JS;=;% & "%_prog%" "%dp0%\\cli.js" %*\n',
            encoding="utf-8",
        )
        return shim

    return SimpleNamespace(
        make=make, prefix=prefix, node=node, hostile_node=hostile_node, marker=marker
    )


@pytest.mark.windows_only(reason="requires real cmd.exe and Windows Node executable search")
@pytest.mark.parametrize("parent_protection", [False, True])
@pytest.mark.parametrize("command", ["pi", "codex"])
def test_real_npm_shim_avoids_checkout_node(
    native_node_shim, monkeypatch, command, parent_protection
):
    fixture = native_node_shim
    shim = fixture.make(command)
    unsafe_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"
    }
    control = subprocess.run(
        [str(shim), "--help"], capture_output=True, text=True, env=unsafe_env, timeout=10
    )
    assert control.returncode == 0, control.stderr
    assert "hostile/runtime" in control.stdout
    assert Path(fixture.marker.read_text()).samefile(fixture.hostile_node)
    fixture.marker.unlink()
    if parent_protection:
        monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "1")
    adapter = dataclasses.replace(
        load_adapters(ADAPTER_DIR)[command],
        models_argv=("--list-models",),
        models_format="lines",
        deny_external_tools_probe_markers=("trusted/runtime",),
    )
    # Codex has no shipped model-list command; assigning one here exercises
    # the shared subprocess boundary with each JavaScript shim shape.
    assert models.list_models(adapter).models == ("trusted/runtime",)
    assert readiness.probe_deny_argv(adapter, str(shim)).supported
    assert not fixture.marker.exists()


@pytest.mark.windows_only(reason="requires real cmd.exe and Windows Node executable search")
def test_real_custom_shim_and_sibling_node_keep_operator_selection(native_node_shim, monkeypatch):
    fixture = native_node_shim
    shim = fixture.make(custom=True)
    # A sibling interpreter must still win, even when PATH's Node is absent.
    shutil.copy2(fixture.node, fixture.prefix / "node.exe")
    entries = os.environ["PATH"].split(os.pathsep)
    monkeypatch.setenv(
        "PATH", os.pathsep.join(entry for entry in entries if Path(entry) != fixture.node.parent)
    )
    assert execresolve.safe_which("pi") == str(shim)
    adapter = dataclasses.replace(
        load_adapters(ADAPTER_DIR)["pi"],
        models_argv=("two words",),
        models_format="lines",
        deny_external_tools_probe_argv=("two words", "--help"),
        deny_external_tools_probe_markers=("trusted/custom",),
    )
    assert models.list_models(adapter).models == ("trusted/custom",)
    assert readiness.probe_deny_argv(adapter, str(shim)).supported
    assert not fixture.marker.exists()
