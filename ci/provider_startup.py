"""Real reviewer CLI startup checks; no credentials or model calls required."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any

from afriend import childenv, execresolve
from afriend.adapters import FriendSpec, build_argv, load_adapters
from afriend.authority import ExternalToolPolicy
from afriend.claimschema import schema_path
from afriend.paths import ADAPTER_DIR
from afriend.spawn import run_process


class StartupFailure(RuntimeError):
    def __init__(self, message: str, record: dict[str, Any]) -> None:
        super().__init__(message)
        self.record = record


def check_launch(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    *,
    expected: str,
    diagnostic: str | None = None,
    timeout_s: float = 30,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    """Require a real startup or a specific rejection, never timeout/crash."""
    result = run_process(argv, stdin_text, timeout_s, cwd, env=env)
    record = {
        "argv": argv,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "orphans_suspected": result.orphans_suspected,
        "duration_s": result.duration_s,
        "failure_reason": result.failure_reason,
        "output_truncated": result.output_truncated,
    }
    text = result.stdout + result.stderr
    failed = (
        result.timed_out
        or result.output_truncated
        or result.orphans_suspected
        or result.exit_code is None
        or result.exit_code < 0
        or not text.strip()
    )
    if expected == "success":
        failed |= result.exit_code != 0
    elif expected == "rejection":
        failed |= result.exit_code not in {1, 2} or not diagnostic or diagnostic not in text
    else:
        raise ValueError(f"unknown startup expectation: {expected}")
    if failed:
        raise StartupFailure(f"expected {expected}: {text[-2000:]}", record)
    return record


def rejection_argv(canonical: list[str], option: str) -> list[str]:
    """Keep canonical controls while forcing parser failure before model use.

    Help alone is insufficient: several CLIs print help even when another
    argument is unsupported. The negative probe must exercise that same
    invocation without help's early exit.
    """
    argv = list(canonical)
    argv[argv.index(option) + 1] = "afriend-startup-invalid"
    return argv


def require_advertised_options(argv: list[str], help_text: str) -> None:
    """Help and invalid enums can both hide unknown flags; check names too."""
    options = {arg.split("=", 1)[0] for arg in argv[1:] if arg.startswith("--") and arg != "--"}
    missing = sorted(
        option
        for option in options
        if not re.search(r"(?<![\w-])" + re.escape(option) + r"(?=[=,\s]|$)", help_text)
    )
    if missing:
        raise RuntimeError(f"canonical options not advertised by installed CLI: {missing}")


def isolated_environment(root: Path) -> dict[str, str]:
    """Keep runtime prerequisites, replace all provider state, pass no keys."""
    env = childenv.build(())
    locations = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "APPDATA": root / "roaming",
        "LOCALAPPDATA": root / "local",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_DATA_HOME": root / "data",
        "XDG_STATE_HOME": root / "state",
        "XDG_CACHE_HOME": root / "cache",
        "CLAUDE_CONFIG_DIR": root / "claude",
        "CODEX_HOME": root / "codex",
        "PI_CODING_AGENT_DIR": root / "pi",
        "OPENCODE_CONFIG_DIR": root / "opencode",
    }
    for key, path in locations.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(
        CI="1",
        NO_COLOR="1",
        DISABLE_AUTOUPDATER="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("claude", "codex", "opencode", "pi"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--require-windows", action="store_true")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "provider": args.provider,
        "platform": platform.platform(),
        "python": sys.version,
        "requested_version": os.environ.get("AF_PROVIDER_VERSION", "latest"),
        "checks": {},
    }
    try:
        if args.require_windows and sys.platform != "win32":
            raise RuntimeError("this gate requires native Windows; cannot skip or emulate it")
        adapter = load_adapters(ADAPTER_DIR)[args.provider]
        executable = execresolve.safe_which(adapter.binary)
        if not executable:
            raise RuntimeError(f"required real CLI is not installed: {adapter.binary}")
        report["executable"] = executable
        work = args.out.resolve() / "work"
        work.mkdir(exist_ok=True)
        env = isolated_environment(args.out.resolve() / "profile")
        prompt = work / "review.txt"
        prompt.write_text(
            "Startup check: this prompt must never reach a model.\n", encoding="utf-8"
        )
        spec = FriendSpec("startup", args.provider, "ops", None, None, "doc", 30)
        policy = (
            ExternalToolPolicy.ALLOW if args.provider == "opencode" else ExternalToolPolicy.DENY
        )
        canonical, stdin_text, _ = build_argv(adapter, spec, prompt, schema_path(work), policy)
        cases = {
            "version": ([executable, "--version"], "success", None),
            "canonical-help": ([*canonical, "--help"], "success", None),
            "invalid-value": (
                rejection_argv(canonical, PROVIDERS[args.provider]["invalid_option"]),
                "rejection",
                "afriend-startup-invalid",
            ),
        }
        for name, (command, expected, diagnostic) in cases.items():
            try:
                record = check_launch(
                    command,
                    work,
                    env,
                    expected=expected,
                    diagnostic=diagnostic,
                    stdin_text=stdin_text if name != "version" else None,
                )
            except StartupFailure as exc:
                report["checks"][name] = exc.record
                raise
            report["checks"][name] = record
            if name == "canonical-help":
                require_advertised_options(canonical, record["stdout"] + record["stderr"])
            print(f"PASS {args.provider}: {name} (exit {record['exit_code']})", flush=True)
        help_text = (
            report["checks"]["canonical-help"]["stdout"]
            + report["checks"]["canonical-help"]["stderr"]
        )
        missing = [
            marker
            for marker in adapter.deny_external_tools_probe_markers
            if marker not in help_text
        ]
        if missing:
            raise RuntimeError(f"installed CLI help lacks required denial controls: {missing}")
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc)
        print(f"FAIL {args.provider}: {exc}", file=sys.stderr)
    finally:
        (args.out / "startup.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if report.get("passed") else 1


PROVIDERS = {
    "claude": {
        "package": "@anthropic-ai/claude-code",
        "invalid_option": "--output-format",
    },
    "codex": {
        "package": "@openai/codex",
        "invalid_option": "--sandbox",
    },
    "opencode": {
        "package": "@opencode/cli",
        "invalid_option": "--format",
    },
    "pi": {
        "package": "@earendil-works/pi-coding-agent",
        "invalid_option": "--mode",
    },
}

if __name__ == "__main__":
    raise SystemExit(main())
