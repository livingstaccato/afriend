"""The Codex half of the activation suite, checked without running Codex.

`claude plugin eval` measures which afriend skill Claude Code selects; nothing
measured Codex, which ships the same skills through its own plugin.
`scripts/run_codex_skill_eval.py` replays the suite through `codex exec --json`.
These exercise how it reads a run, and the guard around one, against real
Codex event streams and a fake `codex`, so no test makes a model call.

`tests/fixtures/codex_skill_eval_real/` holds two real guarded runs of
`afriend resume run-123` (codex-cli 0.154.0), with paths redacted and long
command output truncated. In both, the model tried `afriend status` and the
guard's login shell reported it not found; the second also ran with every
configured MCP server disabled.
"""

import importlib.util
import json
from pathlib import Path
import stat
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
REAL = REPO / "tests" / "fixtures" / "codex_skill_eval_real"
RESUME = "pos-afriend-resume-run-123"
SKILL = (
    "/bin/zsh -lc 'cat <codex-home>/plugins/cache/afriend-local/afriend/0.11.1/skills/{}/SKILL.md'"
)
DONE = {"type": "turn.completed"}


def _module():
    path = REPO / "scripts" / "run_codex_skill_eval.py"
    spec = importlib.util.spec_from_file_location("codex_skill_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _module()


def _cmd(command, output="", exit_code=0, item_id="c1"):
    return {
        "type": "item.completed",
        "item": {
            "id": item_id,
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": "completed",
        },
    }


def _case(expected="afriend:review", tags=("narrow",)):
    return M.Case("pos-x", "afriend resume run-123", tuple(tags), expected)


def test_a_real_run_that_tried_afriend_is_read_as_blocked_not_breached():
    outcome = M.analyse(M.load_events(REAL / "blocked-forbidden-run.jsonl"))

    assert outcome.selected == "afriend:review"
    assert outcome.skills_read == ["review"]
    assert outcome.completed and not outcome.errors
    assert outcome.breaches == []
    assert outcome.blocked == ["/bin/zsh -lc 'afriend status run-123 --json'"]
    assert M.judge(_case(), outcome) == ("ok", None)


def test_a_real_run_with_mcp_disabled_emits_only_permitted_items():
    outcome = M.analyse(M.load_events(REAL / "mcp-disabled-run.jsonl"))

    assert outcome.unpermitted == []
    assert outcome.selected == "afriend:review"
    assert M.judge(_case(), outcome) == ("ok", None)


def test_a_model_cli_the_shell_actually_ran_is_a_breach_even_with_the_right_skill():
    outcome = M.analyse(
        [
            _cmd(SKILL.format("review")),
            _cmd("/bin/zsh -lc 'afriend status run-123 --json'", '{"state": "x"}', 2, "c2"),
            DONE,
        ]
    )

    assert outcome.breaches == ["/bin/zsh -lc 'afriend status run-123 --json'"]
    status, reason = M.judge(_case(), outcome)
    assert status == "untrusted"
    assert "guard breach" in reason


@pytest.mark.parametrize(
    ("command", "programs"),
    [
        (SKILL.format("review"), ["cat"]),
        ("/bin/zsh -lc 'FOO=1 afriend run x'", ["afriend"]),
        ("/bin/zsh -lc 'cd /tmp && codex exec hi'", ["cd", "codex"]),
        ("/bin/zsh -lc 'echo hi | claude -p'", ["echo", "claude"]),
        ("/bin/zsh -lc '/home/u/.local/bin/agy models'", ["agy"]),
        ("/bin/zsh -lc 'env HOME=/x opencode run'", ["opencode"]),
        ("/bin/zsh -lc 'echo \"afriend run\"'", ["echo"]),
    ],
)
def test_only_words_in_command_position_are_programs(command, programs):
    assert M.invoked_programs(command) == programs


def test_a_command_substitution_still_names_its_program():
    assert "agy" in M.invoked_programs("/bin/zsh -lc 'x=$(agy models)'")


def test_an_item_outside_the_allowlist_makes_the_run_untrusted():
    mcp = {"id": "m1", "type": "mcp_tool_call"}
    outcome = M.analyse(
        [
            {"type": "item.started", "item": mcp},
            {"type": "item.completed", "item": mcp},
            _cmd(SKILL.format("review")),
            DONE,
        ]
    )

    assert outcome.unpermitted == ["mcp_tool_call (m1)"]
    assert M.judge(_case(), outcome)[0] == "untrusted"


def test_the_first_afriend_skill_read_is_the_selection():
    outcome = M.analyse([_cmd(SKILL.format("review")), _cmd(SKILL.format("status")), DONE])

    assert outcome.selected == "afriend:review"
    assert M.judge(_case("afriend:status"), outcome) == (
        "wrong",
        "selected afriend:review, expected afriend:status",
    )


def test_a_skill_from_another_plugin_is_not_a_selection():
    other = "/bin/zsh -lc 'cat <codex-home>/plugins/cache/openai-curated/superpowers/1/skills/brainstorming/SKILL.md'"
    outcome = M.analyse([_cmd(other), DONE])

    assert outcome.selected is None
    assert M.judge(_case(None, ("no-activation",)), outcome) == ("ok", None)


def test_a_negative_case_that_reads_an_afriend_skill_is_wrong():
    outcome = M.analyse([_cmd(SKILL.format("review")), DONE])

    assert M.judge(_case(None, ("no-activation",)), outcome) == (
        "wrong",
        "selected afriend:review, expected no afriend skill",
    )


def test_a_run_that_never_completed_is_untrusted():
    unfinished = M.analyse([_cmd(SKILL.format("review"))])
    failed = M.analyse([_cmd(SKILL.format("review")), {"type": "error", "message": "401"}, DONE])

    assert M.judge(_case(), unfinished) == (
        "untrusted",
        "did not complete: no turn.completed event",
    )
    assert M.judge(_case(), failed)[0] == "untrusted"


def test_the_real_suite_pairs_every_case_with_an_expectation():
    cases = M.load_cases()
    negatives = [case for case in cases if case.expected is None]

    assert len(cases) == 18
    assert len(negatives) == 5
    assert all(case.name.startswith("neg-") for case in negatives)
    assert all(case.expected.startswith("afriend:") for case in cases if case.expected)
    resume = next(case for case in cases if case.name == RESUME)
    assert resume.prompt == "afriend resume run-123"
    assert resume.expected == "afriend:review"


def _suite(tmp_path, name, tags):
    case = tmp_path / "evals" / name
    case.mkdir(parents=True)
    case.joinpath("prompt.md").write_text(f"---\ntags: [{tags}]\n---\n\nafriend README.md\n")
    return tmp_path / "evals"


def test_a_positive_case_with_no_expectation_is_refused(tmp_path):
    with pytest.raises(M.Unreadable, match="names no skill"):
        M.load_cases(_suite(tmp_path, "pos-new", "narrow"), {})


def test_an_expectation_naming_no_case_is_refused(tmp_path):
    evals = _suite(tmp_path, "pos-a", "narrow")

    with pytest.raises(M.Unreadable, match="pos-gone"):
        M.load_cases(evals, {"pos-a": "afriend:review", "pos-gone": "afriend:status"})


def test_every_declared_mcp_server_is_disabled(tmp_path):
    tmp_path.joinpath("config.toml").write_text(
        '[mcp_servers.alpha]\ncommand = "a"\n\n[mcp_servers.beta-2]\ncommand = "b"\n'
    )

    assert M.mcp_overrides(tmp_path) == [
        "-c",
        "mcp_servers.alpha.enabled=false",
        "-c",
        "mcp_servers.beta-2.enabled=false",
    ]
    assert M.mcp_overrides(tmp_path / "absent") == []


def test_an_mcp_server_that_cannot_be_addressed_is_refused(tmp_path):
    tmp_path.joinpath("config.toml").write_text('[mcp_servers."a.b"]\ncommand = "a"\n')

    with pytest.raises(M.Unreadable, match="cannot be disabled"):
        M.mcp_overrides(tmp_path)


def test_the_guard_moves_home_and_strips_path(tmp_path):
    base = {"PATH": "/u/.local/bin:/usr/bin", "ZDOTDIR": "/u", "TERM": "xterm"}
    env = M.guard_env(tmp_path / "home", tmp_path / "codex", base)

    assert env["HOME"] == str(tmp_path / "home")
    assert env["CODEX_HOME"] == str(tmp_path / "codex")
    assert env["PATH"] == M.SAFE_PATH
    assert "ZDOTDIR" not in env
    assert env["TERM"] == "xterm"


def test_the_codex_command_is_read_only_ephemeral_and_json(tmp_path):
    argv = M.codex_argv("afriend README.md", tmp_path, tmp_path / "last", ["-c", "k=v"])

    assert argv[:4] == ["codex", "-c", "k=v", "exec"]
    assert {"--json", "--ephemeral"} <= set(argv)
    assert argv[argv.index("-s") + 1] == "read-only"
    assert argv[-1] == "afriend README.md"
    with pytest.raises(M.Unreadable, match="Codex option"):
        M.codex_argv("--help", tmp_path, tmp_path / "last", [])


def _fake_codex(tmp_path, monkeypatch, events, also=()):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    codex = bin_dir / "codex"
    codex.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "record = {'argv': args, 'HOME': os.environ['HOME'], 'home_files': os.listdir(os.environ['HOME'])}\n"
        "record['CODEX_HOME'] = os.environ['CODEX_HOME']\n"
        f"with open({str(calls)!r}, 'a') as log:\n"
        "    log.write(json.dumps(record) + '\\n')\n"
        "pathlib.Path(args[args.index('-o') + 1]).write_text('done')\n"
        f"sys.stdout.write(pathlib.Path({str(events)!r}).read_text())\n"
    )
    for tool in (codex, *(bin_dir / name for name in also)):
        if not tool.exists():
            tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(M, "SAFE_PATH", f"{bin_dir}:/usr/bin:/bin")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    codex_home.joinpath("config.toml").write_text('[mcp_servers.alpha]\ncommand = "a"\n')
    return calls, codex_home


def _main(tmp_path, codex_home, *extra):
    argv = ["--runs", "1", "--codex-home", str(codex_home), "--out", str(tmp_path / "out")]
    return M.main([*argv, *extra], base_env={"SHELL": "/bin/sh"})


def test_a_guarded_run_through_codex_passes_and_records_what_it_blocked(tmp_path, monkeypatch):
    calls, codex_home = _fake_codex(tmp_path, monkeypatch, REAL / "blocked-forbidden-run.jsonl")

    assert _main(tmp_path, codex_home, "--case", RESUME) == 0

    [call] = [json.loads(line) for line in calls.read_text().splitlines()]
    assert call["argv"][:3] == ["-c", "mcp_servers.alpha.enabled=false", "exec"]
    assert call["CODEX_HOME"] == str(codex_home)
    assert call["HOME"] == str(tmp_path / "out" / RESUME / "run-1" / "home")
    assert call["home_files"] == []
    [record] = json.loads((tmp_path / "out" / "summary.json").read_text())["results"]
    assert record["status"] == "ok"
    assert record["blocked"] == ["/bin/zsh -lc 'afriend status run-123 --json'"]


def test_a_wrong_selection_exits_1(tmp_path, monkeypatch):
    _, codex_home = _fake_codex(tmp_path, monkeypatch, REAL / "blocked-forbidden-run.jsonl")

    assert _main(tmp_path, codex_home, "--case", "pos-afriend-status") == 1


def test_the_guard_refuses_to_start_while_a_model_cli_is_reachable(tmp_path, monkeypatch):
    calls, codex_home = _fake_codex(
        tmp_path, monkeypatch, REAL / "blocked-forbidden-run.jsonl", also=("agy",)
    )

    assert _main(tmp_path, codex_home, "--case", RESUME) == 2
    assert not calls.exists()


def test_a_dry_run_calls_nothing(tmp_path, monkeypatch, capsys):
    calls, codex_home = _fake_codex(tmp_path, monkeypatch, REAL / "blocked-forbidden-run.jsonl")

    assert _main(tmp_path, codex_home, "--dry-run", "--tag", "no-activation") == 0
    assert not calls.exists()
    assert capsys.readouterr().out.count("-> no afriend skill") == 5


def test_an_unknown_case_is_refused(tmp_path, monkeypatch):
    _, codex_home = _fake_codex(tmp_path, monkeypatch, REAL / "blocked-forbidden-run.jsonl")

    assert _main(tmp_path, codex_home, "--dry-run", "--case", "pos-nope") == 2
