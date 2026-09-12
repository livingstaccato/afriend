#!/usr/bin/env python3
"""Replay the activation suite through Codex and assert which afriend skill it selected.

`claude plugin eval` measures skill selection for Claude Code only. Codex ships
the same four skills through its own plugin (`plugins/afriend/.codex-plugin`)
and chooses between them from the same `description:` frontmatter; this
measures whether it chooses correctly.

Codex emits no Skill tool event. A selection shows up as a shell command that
reads `.../plugins/cache/afriend-local/afriend/<version>/skills/<name>/SKILL.md`,
so the first afriend skill file a run reads is the skill it selected, and a
`no-activation` case must read none.

Codex runs in a container built from evals/codex/Dockerfile:

    scripts/run_codex_skill_eval.py build           # once per Codex version
    scripts/run_codex_skill_eval.py login           # once: the eval's own Codex login
    scripts/run_codex_skill_eval.py run --dry-run   # print the plan, call nothing
    scripts/run_codex_skill_eval.py run --runs 2

Why a container. The prompts ask for real work -- `afriend resume run-123` --
and on the first full run, on the host, a `configure` case found the installed
`afriend` through CODEX_HOME's path and ran it by absolute path. Hiding the CLIs
from PATH and HOME cannot stop that. In the container there is nothing to find:
no afriend, agy, claude or opencode, no host directory mounted, a read-only root
filesystem, no capabilities, and a Codex login of its own kept in a Docker
volume, so the eval never reads or refreshes the host's credential. The plugin
under test is this checkout's, streamed in as a tar rather than mounted.

Codex's own sandbox cannot start in a container (bwrap needs user namespaces),
so it runs with that sandbox off and the container as the boundary. Each run
still refuses to start if a model CLI is on the container's PATH, and its event
stream is checked: an item outside an allowlist of types, or a model CLI the
shell actually ran, makes the run untrusted.

Exit codes: 0 every selected case completed every run and selected the
expected skill; 1 a run selected the wrong skill; 2 the result cannot be
trusted -- no image, no login, a model CLI in the image, a run that breached,
emitted an item outside the allowlist, or did not complete, or a suite that
disagrees with expectations.json. An untrusted run outranks a wrong selection:
it says nothing reliable about what was selected.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
import contextlib
from dataclasses import asdict, dataclass, field
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
from types import FrameType
import uuid

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "plugins" / "afriend" / "evals"
EXPECTATIONS = EVALS / "expectations.json"
IMAGE_DIR = REPO / "evals" / "codex"
CODEX_VERSION = "0.154.0"
IMAGE = f"afriend-codex-eval:{CODEX_VERSION}"
VOLUME = "afriend-codex-eval-home"
CONTAINER_PREFIX = "afriend-codex-eval-"
CONTAINER_UID = 10001
CONTAINER_HOME = "/home/evaluser"
CONTAINER_CODEX_HOME = f"{CONTAINER_HOME}/.codex"
PIDS_LIMIT = 512
PROMPT_ENV = "EVAL_PROMPT"
MARKETPLACE = "afriend-local"
PLUGIN = f"afriend@{MARKETPLACE}"
# The repository marketplace and the plugin it names: everything Codex needs to
# install this checkout's plugin, and nothing else from the host.
SHIPPED = (".agents/plugins/marketplace.json", "plugins/afriend")
NOT_SHIPPED = frozenset({"results", "__pycache__"})
DEFAULT_RUNS = 2
RUN_TIMEOUT_S = 300
PREFLIGHT_TIMEOUT_S = 60
OUT_PREFIX = "codex-skill-eval-"
# The container script's exit status when a model CLI is on its PATH.
MODEL_CLI_PRESENT = 97
NEGATIVE_TAG = "no-activation"
HIDDEN = ("afriend", "agy", "claude", "opencode")
MODEL_CLIS = frozenset({*HIDDEN, "codex"})
PERMITTED_ITEMS = frozenset({"agent_message", "reasoning", "command_execution", "todo_list"})
AFRIEND_SKILL = re.compile(
    r"/plugins/cache/afriend-local/afriend/[^/\s'\"]+/skills/([a-z][a-z-]*)/SKILL\.md"
)
SEPARATORS = frozenset({";", "&", "&&", "|", "||", "|&", "(", ")", ";;"})
PREFIX_COMMANDS = frozenset({"command", "env", "exec", "nohup", "sudo", "time", "xargs"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

CONTAINER = (
    "--read-only",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    "--pids-limit",
    str(PIDS_LIMIT),
    "--tmpfs",
    "/tmp",
    "--tmpfs",
    f"{CONTAINER_HOME}:uid={CONTAINER_UID},gid={CONTAINER_UID}",
    "-v",
    f"{VOLUME}:{CONTAINER_CODEX_HOME}",
    "-e",
    f"HOME={CONTAINER_HOME}",
    "-e",
    f"CODEX_HOME={CONTAINER_CODEX_HOME}",
)

# Registration is removed before it is added, so a second run against the same
# login volume does not stop on "already added". The prompt arrives in the
# environment, never in the script, so no prompt can be read as shell.
CONTAINER_SCRIPT = f"""set -eu
for name in {" ".join(HIDDEN)}; do
  if command -v "$name" >/dev/null 2>&1; then
    echo "a model CLI is installed in the image: $name" >&2
    exit {MODEL_CLI_PRESENT}
  fi
done
mkdir -p "$HOME/src" "$HOME/work"
tar -x -C "$HOME/src"
codex plugin remove {PLUGIN} >/dev/null 2>&1 || true
codex plugin marketplace remove {MARKETPLACE} >/dev/null 2>&1 || true
codex plugin marketplace add "$HOME/src" >&2
codex plugin add {PLUGIN} >&2
exec codex exec --json --ephemeral --skip-git-repo-check \\
  --dangerously-bypass-approvals-and-sandbox -C "$HOME/work" "${PROMPT_ENV}" </dev/null
"""


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

    Codex reports `<shell> -lc '<script>'`; the script is what is parsed. A word
    is a program when it starts a command -- first, or after a separator --
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
            if program not in MODEL_CLIS:
                continue
            if _not_found(output, program):
                outcome.blocked.append(command)
            else:
                outcome.breaches.append(f"ran {command}")
    if outcome.skills_read:
        outcome.selected = f"afriend:{outcome.skills_read[0]}"
    return outcome


def judge(case: Case, outcome: RunOutcome) -> tuple[str, str | None]:
    """`("ok", None)`, `("wrong", reason)` or `("untrusted", reason)`."""
    if outcome.breaches:
        return "untrusted", f"guard breach: {'; '.join(outcome.breaches)}"
    if outcome.unpermitted:
        return "untrusted", f"items outside the allowlist: {', '.join(outcome.unpermitted)}"
    if outcome.errors or not outcome.completed:
        detail = "; ".join(outcome.errors) or "no turn.completed event"
        return "untrusted", f"did not complete: {detail}"
    if outcome.selected != case.expected:
        want = case.expected or "no afriend skill"
        return "wrong", f"selected {outcome.selected or 'no afriend skill'}, expected {want}"
    return "ok", None


def load_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _ship(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if NOT_SHIPPED & set(Path(member.name).parts):
        return None
    member.uid = member.gid = CONTAINER_UID
    member.uname = member.gname = ""
    return member


def plugin_archive(repo: Path = REPO) -> bytes:
    """This checkout's marketplace and plugin, as the tar the container unpacks."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for relative in SHIPPED:
            if not (repo / relative).exists():
                raise Unreadable(f"{relative} is missing from {repo}")
            archive.add(repo / relative, arcname=relative, filter=_ship)
    return buffer.getvalue()


def build_argv() -> list[str]:
    return [
        "docker",
        "build",
        "--build-arg",
        f"CODEX_VERSION={CODEX_VERSION}",
        "-t",
        IMAGE,
        str(IMAGE_DIR),
    ]


def login_argv(tty: bool) -> list[str]:
    # Docker refuses `-t` when stdin is not a terminal, which is how an editor's
    # shell escape (`! command`) runs it.
    interactive = "-it" if tty else "-i"
    return [
        "docker",
        "run",
        "--rm",
        interactive,
        *CONTAINER,
        IMAGE,
        "codex",
        "login",
        "--device-auth",
    ]


def login_status_argv() -> list[str]:
    return ["docker", "run", "--rm", *CONTAINER, IMAGE, "codex", "login", "status"]


def run_argv(container: str) -> list[str]:
    # `-e NAME` with no value: docker copies it from its own environment, which
    # is where the prompt goes.
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        container,
        *CONTAINER,
        "-e",
        PROMPT_ENV,
        IMAGE,
        "sh",
        "-c",
        CONTAINER_SCRIPT,
    ]


def preflight(env: Mapping[str, str]) -> None:
    """Refuse before any model call unless the image exists and its login works."""
    image = subprocess.run(
        ["docker", "image", "inspect", IMAGE], env=dict(env), capture_output=True, check=False
    )
    if image.returncode != 0:
        raise Unreadable(f"there is no {IMAGE} image; run `{Path(__file__).name} build` first")
    status = subprocess.run(
        login_status_argv(),
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=PREFLIGHT_TIMEOUT_S,
        check=False,
    )
    if status.returncode != 0:
        raise Unreadable(
            f"the eval's Codex login in volume {VOLUME} is missing or expired; run "
            f"`{Path(__file__).name} login`"
        )


def run_once(case: Case, run_dir: Path, archive: bytes, env: Mapping[str, str]) -> RunOutcome:
    run_dir.mkdir(parents=True)
    events = run_dir / "events.jsonl"
    container = f"{CONTAINER_PREFIX}{uuid.uuid4().hex[:12]}"
    timed_out = False
    with events.open("wb") as out, (run_dir / "stderr.txt").open("wb") as err:
        proc = subprocess.Popen(
            run_argv(container),
            env={**env, PROMPT_ENV: case.prompt},
            stdin=subprocess.PIPE,
            stdout=out,
            stderr=err,
        )
        try:
            proc.communicate(input=archive, timeout=RUN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # A killed `docker run` client can leave its container running.
            if proc.poll() is None:
                subprocess.run(
                    ["docker", "kill", container], env=dict(env), capture_output=True, check=False
                )
                proc.wait()
    outcome = analyse(load_events(events))
    if timed_out:
        outcome.errors.append(f"timed out after {RUN_TIMEOUT_S}s")
    elif proc.returncode == MODEL_CLI_PRESENT:
        outcome.breaches.append("a model CLI is installed in the image (see stderr.txt)")
    elif proc.returncode != 0:
        outcome.errors.append(f"the container exited {proc.returncode} (see stderr.txt)")
    return outcome


def _terminate(signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def _exit_on_sigterm() -> Iterator[None]:
    # SIGTERM would otherwise skip every `finally`: the summary and the kill of
    # the container still running.
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _run(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    if args.runs < 1:
        raise Unreadable("--runs must be at least 1")
    cases = select(load_cases(), args.case, args.tag)
    if args.dry_run:
        print(shlex.join(run_argv(f"{CONTAINER_PREFIX}<id>")))
        for case in cases:
            print(f"{case.name} -> {case.expected or 'no afriend skill'}: {case.prompt}")
        return 0
    archive = plugin_archive()
    preflight(env)

    out = args.out or Path(tempfile.mkdtemp(prefix=OUT_PREFIX))
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    wrong: list[str] = []
    untrusted: list[str] = []
    try:
        with _exit_on_sigterm():
            for case in cases:
                for index in range(1, args.runs + 1):
                    outcome = run_once(case, out / case.name / f"run-{index}", archive, env)
                    status, reason = judge(case, outcome)
                    label = f"{case.name} run {index} of {args.runs}"
                    print(
                        f"{label}: {status}" + (f" -- {reason}" if reason else ""), file=sys.stderr
                    )
                    records.append(
                        {"case": case.name, "run": index, "expected": case.expected}
                        | {"status": status, "reason": reason}
                        | asdict(outcome)
                    )
                    if status == "wrong":
                        wrong.append(f"{label}: {reason}")
                    elif status == "untrusted":
                        untrusted.append(f"{label}: {reason}")
    finally:
        summary = {"image": IMAGE, "runs": args.runs, "results": records}
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


def main(argv: Sequence[str], base_env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay the afriend activation suite through Codex, in a container."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help=f"build {IMAGE} from {IMAGE_DIR.relative_to(REPO)}")
    commands.add_parser("login", help=f"log the eval's own Codex account into {VOLUME}, once")
    run = commands.add_parser("run", help="replay the suite")
    run.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    run.add_argument("--case", action="append", default=[], help="repeatable")
    run.add_argument("--tag", action="append", default=[], help="repeatable")
    run.add_argument("--out", type=Path, help="results directory (default: a new temp dir)")
    run.add_argument("--dry-run", action="store_true", help="print the plan; call nothing")
    args = parser.parse_args(argv)
    env = dict(os.environ if base_env is None else base_env)
    try:
        if args.command == "build":
            return subprocess.run(build_argv(), env=env, check=False).returncode
        if args.command == "login":
            return subprocess.run(login_argv(sys.stdin.isatty()), env=env, check=False).returncode
        return _run(args, env)
    except FileNotFoundError as exc:
        print(
            f"error: {exc.filename or 'docker'} is not installed or not on PATH.", file=sys.stderr
        )
        return 2
    except Unreadable as exc:
        print(f"error: {exc}.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
