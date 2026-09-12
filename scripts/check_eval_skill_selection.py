#!/usr/bin/env python3
"""Assert which afriend skill each positive eval case actually selected.

`claude plugin eval`'s `tool_used` grader accepts only a tool name: `input`,
`input_contains`, `args` and `skill` are all rejected by its schema. So the
suite's positive cases prove that *an* afriend skill fired, never which one,
and a narrow prompt that wrongly chose `status` over `review` passes.

This reads the run's `aggregate-result.json`, which maps each case name to the
`tracePath` of every run it launched, and checks the qualified skill name in
those transcripts against `evals/expectations.json`. The mapping comes from
the result file rather than from guessing at directory names: a kept temp dir
is `/tmp/claude-eval-<random>`, one per run, and carries no case name at all.

Run it after an eval run, pointing at the results directory:

    claude plugin eval plugins/afriend --ablation none --keep-temp
    scripts/check_eval_skill_selection.py plugins/afriend/evals/results

Exit codes: 0 every expected case ran, kept every trace, and selected the
expected skill in every run; 1 a run selected the wrong skill; 2 the run
cannot verify that -- a case missing, a trace not kept, no plugin loaded,
results under more than one `results/` directory, or a result file whose
shape this does not recognise. Partial verification is not a pass.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import TypeVar

REPO = Path(__file__).resolve().parents[1]
EXPECTATIONS = REPO / "plugins" / "afriend" / "evals" / "expectations.json"

_T = TypeVar("_T")


def skills_invoked(trace: object) -> list[str]:
    """Every qualified skill name a transcript invoked, in order.

    Walks the whole structure rather than assuming a layout: the transcript
    is JSONL of message objects whose assistant entries carry `content`
    blocks, and a skill invocation is a `tool_use` block named `Skill` whose
    input has a `skill` key. Scanning generically means a harness change to
    the envelope does not silently turn this into a check that passes
    because it found nothing -- `checked` below is what guards that.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "tool_use" and node.get("name") == "Skill":
                value = node.get("input")
                if isinstance(value, dict) and isinstance(value.get("skill"), str):
                    found.append(value["skill"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(trace)
    return found


def load_trace(path: Path) -> list[object]:
    records: list[object] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        try:
            records = [json.loads(path.read_text(encoding="utf-8"))]
        except json.JSONDecodeError:
            return []
    return records


class Unreadable(Exception):
    """This run cannot be checked, for a reason worded so a user can act on it."""


def find_result_file(target: Path) -> Path | None:
    """The `aggregate-result.json` a results path refers to.

    Accepts the file itself, the run directory holding it, or a `results/`
    directory whose children are one ISO-8601-named directory per run.

    It used to return `sorted(target.rglob(...))[-1]`, which orders WHOLE
    paths, so the directory component outranked the timestamp. Pointed one
    level too high -- at a checkout holding both `evals/results/` and the
    mis-targeted `evals/evals/results/` -- it chose `evals/results` because
    "r" sorts after "e", whatever either run's date. Candidates spanning more
    than one results directory are now refused rather than guessed between.
    """
    if target.is_file():
        return target
    direct = target / "aggregate-result.json"
    if direct.is_file():
        return direct
    candidates = list(target.rglob("aggregate-result.json"))
    if not candidates:
        return None
    trees = sorted({path.parent.parent for path in candidates})
    if len(trees) > 1:
        raise Unreadable(
            f"{target} holds results from {len(trees)} different results directories "
            f"({', '.join(str(tree) for tree in trees)}); point this at one of them. "
            "Choosing by path order would check whichever sorts last, not whichever ran last"
        )
    # One results directory: compare run directory NAMES, which are timestamps.
    return max(candidates, key=lambda path: path.parent.name)


def _field(container: object, key: str, kind: type[_T], where: str) -> _T:
    """`container[key]`, or a schema mismatch naming exactly what was absent.

    An absent key and an empty value used to share a diagnosis, and both
    diagnoses were confidently specific: a missing `suite` told the user to
    re-target the plugin directory, and a renamed `arms` told them their
    traces were gone and to rerun with `--keep-temp`. When the harness changes
    its format, neither is true and both send someone to rerun a paid suite.
    """
    if not isinstance(container, dict) or key not in container:
        raise Unreadable(f"schema mismatch: {where} has no `{key}`")
    value = container[key]
    if not isinstance(value, kind):
        raise Unreadable(
            f"schema mismatch: {where} `{key}` is {type(value).__name__}, not {kind.__name__}"
        )
    return value


def _with_arm_traces(case: object, name: str) -> list[Path]:
    """Every trace path the plugin-loaded arm of one case DECLARES.

    Declared, not merely present: filtering to the files that still exist
    let a case that launched three runs be "checked" on whichever one
    survived. The ablation baseline arm runs with no plugin on purpose, so its
    transcript can never contain an afriend skill and is not read.
    """
    arms = _field(case, "arms", dict, f"case `{name}`")
    runs = _field(arms, "with", list, f"case `{name}` `arms`")
    return [
        Path(_field(run, "tracePath", str, f"case `{name}` run {index}"))
        for index, run in enumerate(runs, start=1)
    ]


def check(target: Path, expected: dict[str, str] | None = None) -> int:
    if expected is None:
        expected = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["cases"]

    try:
        result_file = find_result_file(target)
    except Unreadable as exc:
        print(f"error: {exc}.", file=sys.stderr)
        return 2
    if result_file is None:
        print(
            f"error: no aggregate-result.json under {target}. Point this at the "
            "results directory of an eval run; reporting success here would be a "
            "check that cannot fail.",
            file=sys.stderr,
        )
        return 2
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {result_file} is not readable JSON: {exc}", file=sys.stderr)
        return 2

    failures: list[str] = []
    missing: list[str] = []
    unkept: list[str] = []
    checked = 0
    runs_read = 0
    try:
        suite = _field(result, "suite", dict, "the result file")
        plugins = _field(suite, "plugins", list, "`suite`")
        if not plugins:
            print(
                f"error: {result_file} records no plugin under test, so no afriend skill "
                "could have fired and every case would fail for the wrong reason. The "
                "eval target must be the plugin directory (plugins/afriend), not the "
                "suite directory below it.",
                file=sys.stderr,
            )
            return 2
        by_name: dict[str, object] = {
            _field(case, "name", str, f"cases[{index}]"): case
            for index, case in enumerate(_field(result, "cases", list, "the result file"))
        }

        for case, want in sorted(expected.items()):
            if case not in by_name:
                missing.append(case)
                continue
            traces = _with_arm_traces(by_name[case], case)
            if not traces:
                missing.append(f"{case} (no plugin-loaded runs)")
                continue
            gone = [trace for trace in traces if not trace.is_file()]
            if gone:
                unkept.append(f"{case} ({len(gone)} of {len(traces)} run traces gone)")
                continue
            checked += 1
            # Each run on its own. Pooling every run's invocations let one
            # correct choice excuse the others: under `--runs 3`, selecting
            # `afriend:status` twice and `afriend:review` once passed.
            for index, trace in enumerate(traces, start=1):
                runs_read += 1
                invoked = skills_invoked(load_trace(trace))
                label = f"{case} run {index} of {len(traces)}"
                if not invoked:
                    failures.append(f"{label}: no Skill invocation in its trace, expected {want}")
                elif want not in invoked:
                    failures.append(f"{label}: selected {invoked}, expected {want}")
    except Unreadable as exc:
        print(
            f"error: {result_file}: {exc}. The eval harness may have changed its result "
            "format; nothing here says the eval itself was run wrongly, and rerunning it "
            "would not fix this.",
            file=sys.stderr,
        )
        return 2

    if failures:
        print(f"wrong skill selected in {len(failures)} run(s):", file=sys.stderr)
        print(*(f"  {line}" for line in failures), sep="\n", file=sys.stderr)
        if missing or unkept:
            print("the run was also incomplete; see below.", file=sys.stderr)
    # One verified case used to stand in for every one that was never checked:
    # the refusal fired only when NOTHING was, so a run executing two of
    # thirteen cases printed success and exited 0.
    if missing or unkept or checked == 0:
        print(
            f"error: {result_file} does not verify every expected case, so it cannot pass.",
            file=sys.stderr,
        )
        if missing:
            print(f"  never executed: {', '.join(missing)}", file=sys.stderr)
        if unkept:
            print(
                f"  traces not kept (rerun with --keep-temp): {', '.join(unkept)}",
                file=sys.stderr,
            )
        if checked == 0 and not (missing or unkept):
            print(f"  {EXPECTATIONS.name} names no case to check", file=sys.stderr)
    if failures:
        return 1
    if missing or unkept or checked == 0:
        return 2
    print(
        f"all {checked} expected case(s) selected the expected skill in every one of "
        f"{runs_read} run(s)."
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_eval_skill_selection.py <eval-results-dir>", file=sys.stderr)
        return 2
    return check(Path(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
