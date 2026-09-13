"""The Codex half of the activation suite, checked without running Codex.

`claude plugin eval` measures which afriend skill Claude Code selects; nothing
measured Codex, which ships the same skills through its own plugin.
`scripts/run_codex_skill_eval.py` replays the suite through `codex exec --json`
inside a container that holds no other model CLI. These exercise how it reads
a run, the container it builds, and the refusals around both, against real
Codex event streams and a fake `docker`, so no test makes a model call.

`tests/fixtures/codex_skill_eval_real/` holds two real runs of `afriend resume
run-123` (codex-cli 0.154.0, on the host under the guard this replaced), with
paths redacted and long command output truncated. In both, the model tried
`afriend status` and the shell reported it not found.
"""

import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

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


def test_a_real_run_that_tried_afriend_records_an_attempt_not_a_breach():
    outcome = M.analyse(M.load_events(REAL / "blocked-forbidden-run.jsonl"))

    assert outcome.selected == "afriend:review"
    assert outcome.skills_read == ["review"]
    assert outcome.completed and not outcome.errors
    assert outcome.breaches == []
    assert outcome.attempted == ["/bin/zsh -lc 'afriend status run-123 --json'"]
    assert M.judge(_case(), outcome) == ("ok", None)


def test_a_real_run_emits_only_permitted_items():
    outcome = M.analyse(M.load_events(REAL / "mcp-disabled-run.jsonl"))

    assert outcome.unpermitted == []
    assert M.judge(_case(), outcome) == ("ok", None)


def test_command_text_alone_never_makes_a_breach():
    # The real run that led here. `command -v afriend` found nothing, so `&&`
    # never reached `afriend doctor`, and nothing printed "not found" for it:
    # read from its text, a command that never ran looked like one that did.
    outcome = M.analyse(M.load_events(REAL / "container-short-circuit-run.jsonl"))

    assert outcome.breaches == []
    assert outcome.attempted == [
        "/bin/sh -lc 'ls -la /home/evaluser/work && command -v afriend && afriend doctor'"
    ]
    assert M.judge(_case(), outcome) == ("ok", None)


def test_every_model_cli_invocation_is_recorded_as_an_attempt():
    outcome = M.analyse(
        [
            _cmd(SKILL.format("review")),
            _cmd("/bin/sh -lc '/home/u/.local/bin/afriend doctor'", "ready", 0, "c2"),
            DONE,
        ]
    )

    assert outcome.attempted == ["/bin/sh -lc '/home/u/.local/bin/afriend doctor'"]
    assert outcome.breaches == []


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
    other = (
        "/bin/sh -lc 'cat /h/.codex/plugins/cache/openai-curated/superpowers/1/skills/x/SKILL.md'"
    )
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


def test_the_container_is_hardened_and_mounts_nothing_from_the_host():
    argv = M.run_argv("afriend-codex-eval-x")

    assert argv[:4] == ["docker", "run", "--rm", "-i"]
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert "--privileged" not in argv and "--mount" not in argv
    volumes = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-v"]
    assert volumes == [f"{M.VOLUME}:{M.CONTAINER_CODEX_HOME}"]
    # The prompt is copied from docker's environment, never written into argv.
    assert argv[argv.index(M.IMAGE) - 1] == M.PROMPT_ENV
    assert argv[-3:-1] == ["sh", "-c"]


def test_the_container_script_checks_before_and_after_codex_and_reads_the_prompt_from_env():
    script = M.CONTAINER_SCRIPT

    assert '"$EVAL_PROMPT" </dev/null' in script
    assert "--dangerously-bypass-approvals-and-sandbox" in script
    # `exec` would replace the shell, and the check after Codex would never run.
    assert "exec codex" not in script
    first, last = script.index("$(model_clis)"), script.rindex("$(model_clis)")
    assert first < script.index("codex exec") < last


TURN = 'echo \'{"type": "turn.completed"}\''


def _container_script(tmp_path, exec_body, preinstalled=()):
    """Run the container script under /bin/sh with a fake `codex`, no docker needed."""
    home, scratch, bin_dir = tmp_path / "home", tmp_path / "tmp", tmp_path / "bin"
    for directory in (home, scratch, bin_dir):
        directory.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(f'#!/bin/sh\nif [ "$1" = exec ]; then\n{exec_body}\nfi\n')
    for tool in (codex, *(bin_dir / name for name in preinstalled)):
        if not tool.exists():
            tool.write_text("#!/bin/sh\n")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    env = {
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        M.PROMPT_ENV: "afriend README.md",
    }
    return subprocess.run(
        ["/bin/sh", "-c", M.CONTAINER_SCRIPT],
        input=M.plugin_archive(),
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.mark.posix_only(reason="runs a POSIX shell script, which Windows cannot execute")
def test_the_container_passes_codex_through_when_no_model_cli_appears(tmp_path):
    proc = _container_script(tmp_path, TURN)

    assert proc.returncode == 0, proc.stderr
    assert b"turn.completed" in proc.stdout


@pytest.mark.posix_only(reason="runs a POSIX shell script, which Windows cannot execute")
def test_the_container_keeps_codexs_own_exit_status(tmp_path):
    assert _container_script(tmp_path, "exit 3").returncode == 3


@pytest.mark.parametrize(
    "install",
    [
        'mkdir -p "$HOME/.local/bin" && printf "#!/bin/sh\\n" > "$HOME/.local/bin/agy"'
        ' && chmod +x "$HOME/.local/bin/agy"',
        'ln -s /bin/sh "$TMPDIR/claude"',
    ],
)
@pytest.mark.posix_only(reason="runs a POSIX shell script, which Windows cannot execute")
def test_a_model_cli_that_appears_during_the_run_is_a_breach(tmp_path, install):
    proc = _container_script(tmp_path, install)

    assert proc.returncode == M.MODEL_CLI_APPEARED
    assert b"appeared during the run" in proc.stderr


@pytest.mark.posix_only(reason="runs a POSIX shell script, which Windows cannot execute")
def test_a_model_cli_already_present_stops_before_codex_runs(tmp_path):
    proc = _container_script(tmp_path, 'touch "$HOME/codex-ran"', preinstalled=("opencode",))

    assert proc.returncode == M.MODEL_CLI_PRESENT
    assert not (tmp_path / "home" / "codex-ran").exists()


def test_the_login_shares_the_containers_hardening_and_volume():
    assert M.login_argv(tty=True)[-3:] == ["codex", "login", "--device-auth"]
    assert set(M.CONTAINER) <= set(M.login_argv(tty=True))
    assert set(M.CONTAINER) <= set(M.login_status_argv())


def test_the_login_asks_for_a_terminal_only_when_it_has_one():
    # Docker refuses `-t` when stdin is not a terminal, as under `! command`.
    assert M.login_argv(tty=True)[:4] == ["docker", "run", "--rm", "-it"]
    without = M.login_argv(tty=False)
    assert without[:4] == ["docker", "run", "--rm", "-i"]
    assert "-it" not in without and "-t" not in without


@pytest.mark.posix_only(
    reason="fakes docker with a shell script on PATH, which Windows cannot execute"
)
def test_login_without_a_terminal_starts_docker_without_one(tmp_path):
    env, log = _docker(tmp_path)

    assert M.main(["login"], base_env=env) == 0
    [call] = _calls(log)
    assert call["argv"][:3] == ["run", "--rm", "-i"]
    assert call["argv"][-3:] == ["codex", "login", "--device-auth"]


def test_the_plugin_ships_as_an_archive_of_this_checkout():
    with tarfile.open(fileobj=io.BytesIO(M.plugin_archive())) as archive:
        members = archive.getmembers()
    names = {member.name for member in members}

    assert ".agents/plugins/marketplace.json" in names
    assert "plugins/afriend/.codex-plugin/plugin.json" in names
    assert "plugins/afriend/skills/review/SKILL.md" in names
    assert not any({"results", "__pycache__"} & set(Path(name).parts) for name in names)
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
    assert {member.uid for member in members} == {M.CONTAINER_UID}


def test_the_image_installs_the_codex_version_the_script_pins():
    dockerfile = (M.IMAGE_DIR / "Dockerfile").read_text()

    assert "\nFROM node@sha256:" in dockerfile
    assert "\nARG CODEX_VERSION\n" in dockerfile
    assert '"@openai/codex@${CODEX_VERSION}"' in dockerfile
    assert "\nUSER evaluser\n" in dockerfile
    # Codex verifies TLS against the system bundle, which the slim base omits;
    # Node carries its own, so a successful `npm install` proves nothing.
    install = "apt-get install -y --no-install-recommends ca-certificates"
    assert install in dockerfile
    assert dockerfile.index(install) < dockerfile.index("\nUSER evaluser\n")
    assert f"CODEX_VERSION={M.CODEX_VERSION}" in M.build_argv()
    assert M.CODEX_VERSION in M.IMAGE


FAKE_DOCKER = """#!{python}
import io, json, os, sys, tarfile
args = sys.argv[1:]
record = {{"argv": args}}
if args[:2] == ["image", "inspect"]:
    code = int(os.environ.get("FAKE_IMAGE_EXIT", "0"))
elif args[:1] == ["run"] and args[-3:] == ["codex", "login", "status"]:
    code = int(os.environ.get("FAKE_LOGIN_EXIT", "0"))
elif args[:1] == ["run"] and args[-3:] == ["codex", "login", "--device-auth"]:
    code = 0
elif args[:1] == ["run"]:
    data = sys.stdin.buffer.read()
    record["prompt"] = os.environ.get("EVAL_PROMPT")
    record["members"] = tarfile.open(fileobj=io.BytesIO(data)).getnames()
    code = int(os.environ.get("FAKE_RUN_EXIT", "0"))
    if code == 0:
        sys.stdout.write(open(os.environ["FAKE_EVENTS"]).read())
else:
    code = 0
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(record) + "\\n")
sys.exit(code)
"""


def _docker(tmp_path, events="blocked-forbidden-run.jsonl", **overrides):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER.format(python=sys.executable))
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "docker.jsonl"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_DOCKER_LOG": str(log),
        "FAKE_EVENTS": str(REAL / events),
        **overrides,
    }
    return env, log


def _calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _run(tmp_path, env, *extra):
    argv = ["run", "--runs", "1", "--out", str(tmp_path / "out"), *extra]
    return M.main(argv, base_env=env)


@pytest.mark.posix_only(
    reason="fakes docker with a shell script on PATH, which Windows cannot execute"
)
def test_a_run_through_the_container_passes_and_records_what_it_blocked(tmp_path):
    env, log = _docker(tmp_path)

    assert _run(tmp_path, env, "--case", RESUME) == 0

    image, login, run = _calls(log)
    assert image["argv"] == ["image", "inspect", M.IMAGE]
    assert login["argv"][-3:] == ["codex", "login", "status"]
    assert run["prompt"] == "afriend resume run-123"
    assert "plugins/afriend/skills/review/SKILL.md" in run["members"]
    [record] = json.loads((tmp_path / "out" / "summary.json").read_text())["results"]
    assert record["status"] == "ok"
    assert record["attempted"] == ["/bin/zsh -lc 'afriend status run-123 --json'"]


@pytest.mark.posix_only(
    reason="fakes docker with a shell script on PATH, which Windows cannot execute"
)
def test_a_wrong_selection_exits_1(tmp_path):
    env, _ = _docker(tmp_path)

    assert _run(tmp_path, env, "--case", "pos-afriend-status") == 1


@pytest.mark.parametrize(
    ("exit_code", "message"),
    [
        (M.MODEL_CLI_PRESENT, "installed in the image"),
        (M.MODEL_CLI_APPEARED, "appeared in the container"),
    ],
)
@pytest.mark.posix_only(
    reason="fakes docker with a shell script on PATH, which Windows cannot execute"
)
def test_a_model_cli_found_in_the_container_makes_the_run_untrusted(tmp_path, exit_code, message):
    env, _ = _docker(tmp_path, FAKE_RUN_EXIT=str(exit_code))

    assert _run(tmp_path, env, "--case", RESUME) == 2
    [record] = json.loads((tmp_path / "out" / "summary.json").read_text())["results"]
    assert message in record["reason"]


def test_a_dry_run_calls_nothing(tmp_path, capsys):
    env, log = _docker(tmp_path)

    assert _run(tmp_path, env, "--dry-run", "--tag", "no-activation") == 0
    assert _calls(log) == []
    assert capsys.readouterr().out.count("-> no afriend skill") == 5


def test_an_unknown_case_is_refused(tmp_path):
    env, _ = _docker(tmp_path)

    assert _run(tmp_path, env, "--dry-run", "--case", "pos-nope") == 2


@pytest.mark.posix_only(
    reason="fakes docker with a shell script on PATH, which Windows cannot execute"
)
def test_missing_docker_is_reported_not_raised(tmp_path, capsys):
    env = {"PATH": str(tmp_path / "empty")}

    assert _run(tmp_path, env, "--case", RESUME) == 2
    assert "not installed or not on PATH" in capsys.readouterr().err


def test_results_and_bytecode_never_ship(tmp_path):
    for relative in (
        ".agents/plugins/marketplace.json",
        "plugins/afriend/skills/review/SKILL.md",
        "plugins/afriend/evals/results/2026/aggregate-result.json",
        "plugins/afriend/__pycache__/x.pyc",
    ):
        tmp_path.joinpath(relative).parent.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath(relative).write_text("x")

    with tarfile.open(fileobj=io.BytesIO(M.plugin_archive(tmp_path))) as archive:
        names = archive.getnames()

    assert "plugins/afriend/skills/review/SKILL.md" in names
    assert not [name for name in names if "results" in name or "__pycache__" in name]


def test_a_checkout_missing_the_marketplace_is_refused(tmp_path):
    tmp_path.joinpath("plugins/afriend").mkdir(parents=True)

    with pytest.raises(M.Unreadable, match="json is missing from"):
        M.plugin_archive(tmp_path)
