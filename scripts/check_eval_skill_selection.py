#!/usr/bin/env python3
"""Assert which afriend skill each positive eval case actually selected.

`claude plugin eval`'s `tool_used` grader accepts only a tool name: `input`,
`input_contains`, `args` and `skill` are all rejected by its schema. So the
suite's positive cases prove that *an* afriend skill fired, never which one,
and a narrow prompt that wrongly chose `status` over `review` passes.

This reads the traces a run keeps (`--keep-temp`) and checks the qualified
skill name against `evals/expectations.json`. It is a separate script rather
than a grader because the harness cannot express the assertion; run it after
an eval run, pointing at the kept output directory.

Exit codes: 0 all checked cases selected what they should, 1 a mismatch,
2 the directory holds nothing this can check.
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
    because it found nothing -- `found_any` below is what guards that.
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


def check(results_dir: Path) -> int:
    expected = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["cases"]
    failures: list[str] = []
    checked = 0

    for case, want in sorted(expected.items()):
        traces = sorted(results_dir.rglob(f"*{case}*/**/*.jsonl")) or sorted(
            results_dir.rglob(f"*{case}*.jsonl")
        )
        if not traces:
            continue
        invoked = [name for trace in traces for name in skills_invoked(load_trace(trace))]
        checked += 1
        if not invoked:
            failures.append(f"{case}: no Skill invocation in its trace, expected {want}")
        elif want not in invoked:
            failures.append(f"{case}: selected {invoked}, expected {want}")

    if checked == 0:
        print(
            f"error: no case traces found under {results_dir}. Run the suite with "
            "--keep-temp and point this at the kept directory; reporting success "
            "here would be a check that cannot fail.",
            file=sys.stderr,
        )
        return 2
    if failures:
        print(f"wrong skill selected in {len(failures)} of {checked} case(s):", file=sys.stderr)
        print(*(f"  {line}" for line in failures), sep="\n", file=sys.stderr)
        return 1
    print(f"all {checked} checked case(s) selected the expected skill.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_eval_skill_selection.py <kept-results-dir>", file=sys.stderr)
        return 2
    return check(Path(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
