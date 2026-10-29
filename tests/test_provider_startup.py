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


# Diagnostic lines captured from real Windows CLI startup probes (2026-10-28).
REJECTIONS = [
    (
        "claude",
        1,
        "error: option '--output-format <format>' argument 'afriend-startup-invalid' "
        "is invalid. Allowed choices are text, json, stream-json.\n",
    ),
    (
        "codex",
        2,
        "error: invalid value 'afriend-startup-invalid' for '--sandbox <SANDBOX_MODE>'\n"
        "  [possible values: read-only, workspace-write, danger-full-access]\n"
        "\nFor more information, try '--help'.\n",
    ),
    (
        "opencode",
        1,
        '\nERROR\n  Invalid value for flag --format: "afriend-startup-invalid". '
        'Expected: "default" | "json"\n',
    ),
    (
        "pi",
        1,
        'Error: Invalid mode "afriend-startup-invalid". Valid values: text, json, rpc\n',
    ),
]


@pytest.mark.parametrize("provider,exit_code,stderr", REJECTIONS)
def test_expected_rejection_accepts_measured_provider_diagnostic(
    tmp_path, provider, exit_code, stderr
):
    result = launch(
        tmp_path,
        f"import sys; sys.stderr.write({stderr!r}); sys.exit({exit_code})",
        expected="rejection",
        diagnostic_regex=MODULE.PROVIDERS[provider]["rejection_regex"],
    )
    assert result["exit_code"] == exit_code
    assert result["stderr"] == stderr


@pytest.mark.parametrize(
    "provider,text",
    [
        ("claude", "error: invalid value afriend-startup-invalid for --model"),
        ("codex", "error: invalid value 'afriend-startup-invalid' for '--model <MODEL>'"),
        ("opencode", 'Invalid value for flag --model: "afriend-startup-invalid".'),
        ("pi", 'Error: Invalid model "afriend-startup-invalid". Valid values: text, json, rpc'),
        ("pi", "argv: --mode afriend-startup-invalid\nError: no credentials"),
        ("codex", "--sandbox <SANDBOX_MODE>\n[examples: afriend-startup-invalid]"),
        (
            "claude",
            "afriend-startup-invalid\nerror: option '--output-format <format>' "
            "argument 'other' is invalid. Allowed choices are text, json, stream-json.",
        ),
    ],
)
def test_unrelated_or_misleading_diagnostics_fail_the_gate(tmp_path, provider, text):
    with pytest.raises(MODULE.StartupFailure):
        launch(
            tmp_path,
            f"import sys; sys.stderr.write({text!r}); sys.exit(1)",
            expected="rejection",
            diagnostic_regex=MODULE.PROVIDERS[provider]["rejection_regex"],
        )


@pytest.mark.parametrize("provider,exit_code,stderr", REJECTIONS)
def test_valid_diagnostic_followed_by_unhandled_crash_fails(tmp_path, provider, exit_code, stderr):
    with pytest.raises(MODULE.StartupFailure):
        launch(
            tmp_path,
            f"import sys; sys.stderr.write({stderr!r}); raise RuntimeError('startup failed')",
            expected="rejection",
            diagnostic_regex=MODULE.PROVIDERS[provider]["rejection_regex"],
        )


@pytest.mark.parametrize(
    "stack",
    [
        "    at [eval]:1:7\n    at node:internal/main/eval_string:74:3\n\nNode.js v22.0.0\n",
        "----- Native stack trace -----\n 1: 00007FF612345678 node::Abort()\n",
        "thread 'main' panicked at src/main.rs:42:5:\nstack backtrace:\n",
    ],
)
def test_matching_diagnostic_with_unhandled_stack_fails(tmp_path, stack):
    stderr = (
        'Error: Invalid mode "afriend-startup-invalid". Valid values: text, json, rpc\n' + stack
    )
    with pytest.raises(MODULE.StartupFailure):
        launch(
            tmp_path,
            f"import sys; sys.stderr.write({stderr!r}); sys.exit(1)",
            expected="rejection",
            diagnostic_regex=MODULE.PROVIDERS["pi"]["rejection_regex"],
        )


def test_real_node_unhandled_enum_error_is_not_a_parser_rejection(tmp_path):
    from afriend.execresolve import safe_which

    node = safe_which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    with pytest.raises(MODULE.StartupFailure):
        MODULE.check_launch(
            [
                node,
                "-e",
                'throw new Error(\'Invalid mode "afriend-startup-invalid". '
                "Valid values: text, json, rpc')",
            ],
            tmp_path,
            dict(os.environ),
            expected="rejection",
            diagnostic_regex=MODULE.PROVIDERS["pi"]["rejection_regex"],
        )


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
        launch(tmp_path, code, expected=expected, diagnostic_regex=diagnostic)


def test_missing_binary_is_not_an_expected_provider_rejection(tmp_path):
    with pytest.raises(RuntimeError):
        MODULE.check_launch(
            [str(tmp_path / "missing-provider")],
            tmp_path,
            dict(os.environ),
            expected="rejection",
            diagnostic_regex="afriend-invalid",
        )


def test_timeout_is_not_an_expected_provider_rejection(tmp_path):
    with pytest.raises(RuntimeError):
        launch(
            tmp_path,
            "import time; time.sleep(30)",
            expected="rejection",
            diagnostic_regex="afriend-invalid",
            timeout_s=0.1,
        )


def test_unhandled_exception_echoing_probe_arguments_is_not_a_parser_rejection(tmp_path):
    with pytest.raises(MODULE.StartupFailure):
        launch(
            tmp_path,
            "raise RuntimeError(['--mode', 'afriend-startup-invalid'])",
            expected="rejection",
            diagnostic_regex=MODULE.PROVIDERS["pi"]["rejection_regex"],
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
