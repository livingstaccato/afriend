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

Exit codes: 0 all checked cases selected what they should, 1 a mismatch,
2 the run holds nothing this can check.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
EXPECTATIONS = REPO / "plugins" / "afriend" / "evals" / "expectations.json"


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


def find_result_file(target: Path) -> Path | None:
    """The `aggregate-result.json` a results path refers to, newest last.

    Accepts the file itself, the single run directory that holds it, or the
    `results/` parent -- whose children are ISO-8601 timestamps, so the
    lexicographic maximum is the most recent run.
    """
    if target.is_file():
        return target
    direct = target / "aggregate-result.json"
    if direct.is_file():
        return direct
    candidates = sorted(target.rglob("aggregate-result.json"))
    return candidates[-1] if candidates else None


def _with_arm_traces(case: object) -> list[Path]:
    """Trace paths for the plugin-loaded arm of one case.

    The ablation baseline arm runs with no plugin on purpose, so its
    transcript can never contain an afriend skill and must not be read as
    evidence that one failed to fire.
    """
    if not isinstance(case, dict):
        return []
    arms = case.get("arms")
    if not isinstance(arms, dict):
        return []
    runs = arms.get("with")
    if not isinstance(runs, list):
        return []
    paths: list[Path] = []
    for run in runs:
        if isinstance(run, dict) and isinstance(run.get("tracePath"), str):
            paths.append(Path(run["tracePath"]))
    return paths


def check(target: Path) -> int:
    expected = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["cases"]

    result_file = find_result_file(target)
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

    suite = result.get("suite") if isinstance(result.get("suite"), dict) else {}
    if not suite.get("plugins"):
        print(
            f"error: {result_file} records no plugin under test, so no afriend skill "
            "could have fired and every case would fail for the wrong reason. The "
            "eval target must be the plugin directory (plugins/afriend), not the "
            "suite directory below it.",
            file=sys.stderr,
        )
        return 2

    cases = result.get("cases")
    by_name = {
        case["name"]: case
        for case in (cases if isinstance(cases, list) else [])
        if isinstance(case, dict) and isinstance(case.get("name"), str)
    }

    failures: list[str] = []
    unkept: list[str] = []
    checked = 0

    for case, want in sorted(expected.items()):
        if case not in by_name:
            continue
        traces = [path for path in _with_arm_traces(by_name[case]) if path.is_file()]
        if not traces:
            unkept.append(case)
            continue
        invoked = [name for trace in traces for name in skills_invoked(load_trace(trace))]
        checked += 1
        if not invoked:
            failures.append(f"{case}: no Skill invocation in its trace, expected {want}")
        elif want not in invoked:
            failures.append(f"{case}: selected {invoked}, expected {want}")

    if checked == 0:
        detail = (
            f"{len(unkept)} case(s) ran but their traces are gone -- rerun with --keep-temp"
            if unkept
            else f"the run covered no case named in {EXPECTATIONS.name}"
        )
        print(
            f"error: nothing to check in {result_file}: {detail}. Reporting success "
            "here would be a check that cannot fail.",
            file=sys.stderr,
        )
        return 2
    if failures:
        print(f"wrong skill selected in {len(failures)} of {checked} case(s):", file=sys.stderr)
        print(*(f"  {line}" for line in failures), sep="\n", file=sys.stderr)
        return 1
    skipped = f" ({len(unkept)} without a kept trace)" if unkept else ""
    print(f"all {checked} checked case(s) selected the expected skill{skipped}.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_eval_skill_selection.py <eval-results-dir>", file=sys.stderr)
        return 2
    return check(Path(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
