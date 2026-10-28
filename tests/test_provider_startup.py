"""The startup gate must reject hangs, crashes, and misleading success."""

import importlib.util
import os
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    "provider_startup", Path(__file__).resolve().parents[1] / "ci/provider_startup.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def launch(tmp_path, code, **kwargs):
    return MODULE.check_launch([sys.executable, "-c", code], tmp_path, dict(os.environ), **kwargs)


def test_startup_records_actual_child_output(tmp_path):
    result = launch(tmp_path, "print('startup version 1.2.3')", expected="success")
    assert result["exit_code"] == 0
    assert result["stdout"].splitlines() == ["startup version 1.2.3"]


def test_expected_rejection_requires_the_declared_diagnostic(tmp_path):
    result = launch(
        tmp_path,
        "import sys; print('invalid choice: afriend-invalid', file=sys.stderr); sys.exit(2)",
        expected="rejection",
        diagnostic="afriend-invalid",
    )
    assert result["exit_code"] == 2
    assert "afriend-invalid" in result["stderr"]


@pytest.mark.parametrize(
    "code,expected,diagnostic",
    [
        ("print('accepted invalid request')", "rejection", "afriend-invalid"),
        ("import sys; sys.exit(2)", "rejection", "afriend-invalid"),
        (
            "import sys; print('unrelated startup crash'); sys.exit(1)",
            "rejection",
            "afriend-invalid",
        ),
        ("import sys; print('failed'); sys.exit(1)", "success", None),
        (
            "import sys; print('afriend-invalid'); sys.exit(17)",
            "rejection",
            "afriend-invalid",
        ),
        ("pass", "success", None),
    ],
)
def test_unexpected_results_fail_the_gate(tmp_path, code, expected, diagnostic):
    with pytest.raises(RuntimeError):
        launch(tmp_path, code, expected=expected, diagnostic=diagnostic)


def test_missing_binary_is_not_an_expected_provider_rejection(tmp_path):
    with pytest.raises(RuntimeError):
        MODULE.check_launch(
            [str(tmp_path / "missing-provider")],
            tmp_path,
            dict(os.environ),
            expected="rejection",
            diagnostic="afriend-invalid",
        )


def test_timeout_is_not_an_expected_provider_rejection(tmp_path):
    with pytest.raises(RuntimeError):
        launch(
            tmp_path,
            "import time; time.sleep(30)",
            expected="rejection",
            diagnostic="afriend-invalid",
            timeout_s=0.1,
        )


def test_startup_profile_excludes_credentials_and_host_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-cli")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-the-cli")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "operator-profile"))
    env = MODULE.isolated_environment(tmp_path / "isolated")
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["PI_CODING_AGENT_DIR"] == str(tmp_path / "isolated/pi")
    assert Path(env["HOME"]).is_dir()
    assert list(Path(env["PI_CODING_AGENT_DIR"]).iterdir()) == []


def test_rejection_probe_preserves_every_other_canonical_argument():
    argv = ["pi", "--print", "--mode", "json", "--no-mcp", "--unexpected-canonical-flag"]
    assert MODULE.rejection_argv(argv, "--mode") == [
        "pi",
        "--print",
        "--mode",
        "afriend-startup-invalid",
        "--no-mcp",
        "--unexpected-canonical-flag",
    ]
    assert argv[3] == "json"


def test_rejection_probe_cannot_silently_drop_an_absent_canonical_option():
    with pytest.raises(ValueError):
        MODULE.rejection_argv(["pi", "--print"], "--mode")


def test_canonical_unknown_flag_cannot_hide_behind_help_or_invalid_enum():
    with pytest.raises(RuntimeError, match="--unsupported-control"):
        MODULE.require_advertised_options(
            ["pi", "--print", "--mode", "json", "--unsupported-control"],
            "Options: --print --mode <format>",
        )


def test_advertised_option_requires_its_own_name_not_a_prefix():
    with pytest.raises(RuntimeError, match="--model"):
        MODULE.require_advertised_options(["pi", "--model", "test"], "--model-provider <name>")


def test_advertised_options_accept_help_punctuation_and_equal_values():
    MODULE.require_advertised_options(
        ["pi", "--print", "--mode=json"], "-p, --print, --mode=<format>\n"
    )
