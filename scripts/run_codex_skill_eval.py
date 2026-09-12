#!/usr/bin/env python3
"""Replay the activation suite through Codex and assert which afriend skill it selected.

`claude plugin eval` measures skill selection for Claude Code only. Codex ships
the same four skills through its own plugin (`plugins/afriend/.codex-plugin`)
and chooses between them from the same `description:` frontmatter, and nothing
measured whether it chooses correctly. This sends each prompt in
plugins/afriend/evals/ through `codex exec --json` and reads the event stream.

Codex emits no Skill tool event. A selection shows up as a shell command that
reads `.../plugins/cache/afriend-local/afriend/<version>/skills/<name>/SKILL.md`,
so the first afriend skill file a run reads is the skill it selected, and a
`no-activation` case must read none.

Every run makes a real model call on your Codex subscription:

    scripts/run_codex_skill_eval.py --dry-run          # print the plan, call nothing
    scripts/run_codex_skill_eval.py --runs 2           # the whole suite, twice per case
    scripts/run_codex_skill_eval.py --tag narrow --runs 1

The guard, and why each part exists:

- `-s read-only` and `--ephemeral`: the run writes nothing and keeps no session.
- `HOME` is a fresh empty directory per run. Codex runs every command through
  the user's login shell, and a login shell's profile puts `~/.local/bin` back
  on PATH, so stripping PATH alone still let a prompt run the installed
  `afriend`. With HOME moved no profile is read; `CODEX_HOME` keeps auth and the
  plugin cache where they are. Before any model call, a login shell under the
  guard must fail to find `afriend`, `agy`, `claude` and `opencode`.
- Every MCP server declared in `CODEX_HOME/config.toml` is disabled with `-c`,
  because MCP tools run outside the shell sandbox. A server that a bundled
  plugin provides cannot be switched off that way, so every item in the event
  stream is also checked against an allowlist of types.
- A command that invokes a model CLI is a guard breach unless the shell reported
  it was not found.

Exit codes: 0 every selected case completed every run inside the guard and
selected the expected skill; 1 a run selected the wrong skill; 2 the result
cannot be trusted -- the guard pre-check failed, a run breached the guard,
emitted an item outside the allowlist, or did not complete, or the suite and
expectations.json disagree. A breach outranks a wrong selection: a run that
escaped its guard says nothing reliable about what it selected.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import contextlib
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import tomllib

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "plugins" / "afriend" / "evals"
EXPECTATIONS = EVALS / "expectations.json"
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_RUNS = 2
RUN_TIMEOUT_S = 300
PRECHECK_TIMEOUT_S = 30
# Enough for Codex and the system tools, and deliberately not ~/.local/bin,
# where `afriend` and the other model CLIs are installed.
SAFE_PATH = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
FALLBACK_SHELL = "/bin/sh"
NEGATIVE_TAG = "no-activation"
MODEL_CLIS = frozenset({"afriend", "agy", "claude", "opencode", "codex"})
# `codex` has to stay reachable to run the suite at all, so the pre-check
# cannot demand it is hidden; a run that invokes it is still caught as a breach.
HIDDEN_BY_GUARD = ("afriend", "agy", "claude", "opencode")
PERMITTED_ITEMS = frozenset({"agent_message", "reasoning", "command_execution", "todo_list"})
AFRIEND_SKILL = re.compile(
    r"/plugins/cache/afriend-local/afriend/[^/\s'\"]+/skills/([a-z][a-z-]*)/SKILL\.md"
)
SEPARATORS = frozenset({";", "&", "&&", "|", "||", "|&", "(", ")", ";;"})
PREFIX_COMMANDS = frozenset({"command", "env", "exec", "nohup", "sudo", "time", "xargs"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
SERVER_NAME = re.compile(r"[A-Za-z0-9_-]+")


class Unreadable(Exception):
    """The suite or a run cannot be evaluated, for a reason worded so a user can act on it."""


@dataclass(frozen=True)
class Case:
    name: str
    prompt: str
    tags: tuple[str, ...]
    # The qualified skill a run must select, or None: it must select no afriend skill.
    expected: str | None


@dataclass
class RunOutcome:
    selected: str | None = None
    skills_read: list[str] = field(default_factory=list)
    completed: bool = False
    errors: list[str] = field(default_factory=list)
    unpermitted: list[str] = field(default_factory=list)
    breaches: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


def _front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    return text[4:end], text[end + 5 :]


def load_cases(
    evals_dir: Path = EVALS, expectations: Mapping[str, str] | None = None
) -> list[Case]:
    """Every case in the suite, each paired with the skill it must select.

    A case tagged `no-activation` must select nothing; every other case must be
    named in expectations.json, and every name there must be a case. Either
    mismatch is refused rather than skipped, because a case silently dropped
    from the comparison is a case that silently passes.
    """
    if expectations is None:
        expectations = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["cases"]
    cases: list[Case] = []
    for directory in sorted(path.parent for path in evals_dir.glob("*/prompt.md")):
        header, body = _front_matter((directory / "prompt.md").read_text(encoding="utf-8"))
        listed = re.search(r"^tags:\s*\[([^\]]*)\]", header, re.MULTILINE)
        tags = tuple(tag.strip() for tag in listed.group(1).split(",")) if listed else ()
        name = directory.name
        if NEGATIVE_TAG in tags:
            expected: str | None = None
        elif name in expectations:
            expected = expectations[name]
        else:
            raise Unreadable(
                f"case `{name}` is not tagged `{NEGATIVE_TAG}` and {EXPECTATIONS.name} "
                "names no skill for it"
            )
        cases.append(Case(name, body.strip(), tuple(tag for tag in tags if tag), expected))
    unknown = sorted(set(expectations) - {case.name for case in cases if case.expected})
    if unknown:
        raise Unreadable(
            f"{EXPECTATIONS.name} names cases with no positive prompt: {', '.join(unknown)}"
        )
    return cases


def select(cases: Sequence[Case], names: Sequence[str], tags: Sequence[str]) -> list[Case]:
    unknown = sorted(set(names) - {case.name for case in cases})
    if unknown:
        raise Unreadable(f"no such case: {', '.join(unknown)}")
    chosen = [
        case
        for case in cases
        if (not names or case.name in names) and (not tags or set(tags) & set(case.tags))
    ]
    if not chosen:
        raise Unreadable("the selection matches no case")
    return chosen


def invoked_programs(command: str) -> list[str]:
    """The program each simple command in a shell command line runs, by basename.

    Codex reports `/bin/zsh -lc '<script>'`; the script is what is parsed. A
    word is a program when it starts a command -- first, or after a separator --
    past any `VAR=value` assignments and prefixes such as `env`. So the
    `afriend` inside `cat .../afriend-local/afriend/.../SKILL.md` is a path, not
    an invocation, while `/home/u/.local/bin/afriend status` is one.
    """
    script = command
    try:
        outer = shlex.split(command)
    except ValueError:
        outer = []
    if len(outer) == 3 and outer[1] in ("-c", "-lc"):
        script = outer[2]
    lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = script.split()
    programs: list[str] = []
    expecting = True
    for token in tokens:
        if token in SEPARATORS:
            expecting = True
        elif expecting and not (ASSIGNMENT.match(token) or token in PREFIX_COMMANDS):
            programs.append(Path(token.lstrip("`")).name)
            expecting = False
    return programs


def _not_found(output: str, program: str) -> bool:
    # zsh, bash and dash respectively.
    return any(
        marker in output
        for marker in (
            f"command not found: {program}",
            f"{program}: command not found",
            f"{program}: not found",
        )
    )


def analyse(events: Sequence[Mapping[str, object]]) -> RunOutcome:
    outcome = RunOutcome()
    for event in events:
        kind = event.get("type")
        if kind == "turn.completed":
            outcome.completed = True
        elif kind in ("error", "turn.failed"):
            outcome.errors.append(json.dumps(event)[:300])
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type not in PERMITTED_ITEMS:
            label = f"{item_type} ({item.get('id')})"
            if label not in outcome.unpermitted:
                outcome.unpermitted.append(label)
            continue
        if kind != "item.completed" or item_type != "command_execution":
            continue
        command = str(item.get("command", ""))
        outcome.skills_read.extend(AFRIEND_SKILL.findall(command))
        output = str(item.get("aggregated_output", ""))
        for program in invoked_programs(command):
            if program in MODEL_CLIS:
                target = outcome.blocked if _not_found(output, program) else outcome.breaches
                target.append(command)
    if outcome.skills_read:
        outcome.selected = f"afriend:{outcome.skills_read[0]}"
    return outcome


def judge(case: Case, outcome: RunOutcome) -> tuple[str, str | None]:
    """`("ok", None)`, `("wrong", reason)` or `("untrusted", reason)`."""
    if outcome.breaches:
        return "untrusted", f"guard breach, ran: {'; '.join(outcome.breaches)}"
    if outcome.unpermitted:
        return "untrusted", f"items outside the allowlist: {', '.join(outcome.unpermitted)}"
    if outcome.errors or not outcome.completed:
        detail = "; ".join(outcome.errors) or "no turn.completed event"
        return "untrusted", f"did not complete: {detail}"
    if outcome.selected != case.expected:
        want = case.expected or "no afriend skill"
        return "wrong", f"selected {outcome.selected or 'no afriend skill'}, expected {want}"
    return "ok", None


def guard_env(home: Path, codex_home: Path, base: Mapping[str, str]) -> dict[str, str]:
    # ZDOTDIR would point zsh back at the real profile the moved HOME hides.
    env = {key: value for key, value in base.items() if key != "ZDOTDIR"}
    env.update(HOME=str(home), CODEX_HOME=str(codex_home), PATH=SAFE_PATH)
    return env


def reachable_under_guard(env: Mapping[str, str]) -> list[str]:
    """The model CLIs a login shell under this environment can still find."""
    shell = env.get("SHELL") or FALLBACK_SHELL
    probe = " ".join(
        f"command -v {name} >/dev/null 2>&1 && echo {name};" for name in HIDDEN_BY_GUARD
    )
    proc = subprocess.run(
        [shell, "-lc", probe],
        env=dict(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=PRECHECK_TIMEOUT_S,
        check=False,
    )
    return proc.stdout.split()


def mcp_overrides(codex_home: Path) -> list[str]:
    config = codex_home / "config.toml"
    if not config.is_file():
        return []
    try:
        servers = tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers", {})
    except tomllib.TOMLDecodeError as exc:
        raise Unreadable(f"{config} is not valid TOML: {exc}") from exc
    overrides: list[str] = []
    for name in sorted(servers):
        if not SERVER_NAME.fullmatch(name):
            raise Unreadable(
                f"MCP server `{name}` in {config} cannot be addressed with `-c`, so it "
                "cannot be disabled for the run"
            )
        overrides += ["-c", f"mcp_servers.{name}.enabled=false"]
    return overrides


def codex_argv(
    prompt: str, workdir: Path, last_message: Path, overrides: Sequence[str]
) -> list[str]:
    if prompt.startswith("-"):
        raise Unreadable(f"prompt {prompt!r} would be parsed as a Codex option")
    return [
        "codex",
        *overrides,
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-C",
        str(workdir),
        "-o",
        str(last_message),
        prompt,
    ]


def load_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _end_group(pid: int, sig: signal.Signals) -> None:
    # MCP servers and other children can outlive Codex; its session is theirs too.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def run_once(
    case: Case,
    run_dir: Path,
    codex_home: Path,
    overrides: Sequence[str],
    base_env: Mapping[str, str],
) -> RunOutcome:
    home, work = run_dir / "home", run_dir / "work"
    home.mkdir(parents=True)
    work.mkdir()
    events = run_dir / "events.jsonl"
    argv = codex_argv(case.prompt, work, run_dir / "last-message.txt", overrides)
    timed_out = False
    with events.open("w", encoding="utf-8") as out, (run_dir / "stderr.txt").open("w") as err:
        try:
            proc = subprocess.Popen(
                argv,
                env=guard_env(home, codex_home, base_env),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise Unreadable(f"`codex` is not on the guarded PATH ({SAFE_PATH})") from exc
        try:
            code = proc.wait(timeout=RUN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
            _end_group(proc.pid, signal.SIGKILL)
            code = proc.wait()
        _end_group(proc.pid, signal.SIGTERM)
    outcome = analyse(load_events(events))
    if timed_out:
        outcome.errors.append(f"timed out after {RUN_TIMEOUT_S}s")
    elif code != 0:
        outcome.errors.append(f"codex exited {code}")
    return outcome


def main(argv: Sequence[str], base_env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay the afriend activation suite through Codex."
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--case", action="append", default=[], help="repeatable")
    parser.add_argument("--tag", action="append", default=[], help="repeatable")
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--out", type=Path, help="results directory (default: a new temp dir)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; call nothing")
    args = parser.parse_args(argv)
    env = dict(os.environ if base_env is None else base_env)

    if args.runs < 1:
        print("error: --runs must be at least 1.", file=sys.stderr)
        return 2
    try:
        cases = select(load_cases(), args.case, args.tag)
        overrides = mcp_overrides(args.codex_home)
        if args.dry_run:
            for case in cases:
                command = codex_argv(case.prompt, Path("<work>"), Path("<last>"), overrides)
                print(f"{case.name} -> {case.expected or 'no afriend skill'}")
                print(f"  {shlex.join(command)}")
            return 0
    except Unreadable as exc:
        print(f"error: {exc}.", file=sys.stderr)
        return 2

    out = args.out or Path(tempfile.mkdtemp(prefix="codex-skill-eval-"))
    out.mkdir(parents=True, exist_ok=True)
    probe_home = out / "precheck-home"
    probe_home.mkdir(exist_ok=True)
    reachable = reachable_under_guard(guard_env(probe_home, args.codex_home, env))
    if reachable:
        print(
            f"error: a login shell under the guard still finds {', '.join(reachable)}, so a "
            "prompt could run it. Nothing was called.",
            file=sys.stderr,
        )
        return 2

    records: list[dict[str, object]] = []
    wrong: list[str] = []
    untrusted: list[str] = []
    try:
        for case in cases:
            for index in range(1, args.runs + 1):
                run_dir = out / case.name / f"run-{index}"
                outcome = run_once(case, run_dir, args.codex_home, overrides, env)
                status, reason = judge(case, outcome)
                label = f"{case.name} run {index} of {args.runs}"
                print(f"{label}: {status}" + (f" -- {reason}" if reason else ""), file=sys.stderr)
                records.append(
                    {"case": case.name, "run": index, "expected": case.expected}
                    | {"status": status, "reason": reason}
                    | asdict(outcome)
                )
                if status == "wrong":
                    wrong.append(f"{label}: {reason}")
                elif status == "untrusted":
                    untrusted.append(f"{label}: {reason}")
    except Unreadable as exc:
        print(f"error: {exc}.", file=sys.stderr)
        return 2
    finally:
        summary = {"runs": args.runs, "mcp_overrides": overrides, "results": records}
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"results: {out}", file=sys.stderr)

    if wrong:
        print(f"wrong skill selected in {len(wrong)} run(s):", file=sys.stderr)
        print(*(f"  {line}" for line in wrong), sep="\n", file=sys.stderr)
    if untrusted:
        print(f"{len(untrusted)} run(s) cannot be trusted:", file=sys.stderr)
        print(*(f"  {line}" for line in untrusted), sep="\n", file=sys.stderr)
        return 2
    if wrong:
        return 1
    print(
        f"all {len(cases)} case(s) selected the expected skill in every one of "
        f"{len(records)} run(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
