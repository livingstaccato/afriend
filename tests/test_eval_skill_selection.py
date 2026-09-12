"""The assertion `claude plugin eval` cannot make.

`tool_used` accepts only a tool name, so every positive activation case is
graded on "some Skill fired". A prompt that wrongly routed `afriend resume
run-123` to `afriend:resolve` instead of `afriend:review` scored exactly the
same as the correct selection. `scripts/check_eval_skill_selection.py` adds
the missing check, and these exercise its rejection behaviour against
synthetic runs so it costs nothing to verify -- a checker whose failure path
has never run is the thing it exists to prevent.

The fixtures mirror the real shape: a results directory holding
`aggregate-result.json`, whose cases carry the `tracePath` of each run. That
file is the only thing linking a case to its transcript, because a kept temp
directory is `/tmp/claude-eval-<random>` and names no case.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "plugins" / "afriend" / "evals"


def _module():
    path = REPO / "scripts" / "check_eval_skill_selection.py"
    spec = importlib.util.spec_from_file_location("eval_skill_selection", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_trace(path: Path, *skills: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": skill, "args": "x"}}
                ]
            },
        }
        for skill in skills
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _run(tmp_path: Path, cases: dict[str, tuple[str, ...]], *, plugin: bool = True) -> Path:
    """A results directory for a run of `cases`, each mapped to its skills."""
    results = tmp_path / "results" / "2026-01-01T00-00-00-000Z"
    results.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (case, skills) in enumerate(cases.items()):
        trace = tmp_path / f"claude-eval-{index}" / "out" / "trace.jsonl"
        _write_trace(trace, *skills)
        entries.append(
            {
                "name": case,
                "arms": {"with": [{"score": 1, "tracePath": str(trace)}]},
            }
        )
    payload = {
        "suite": {"plugins": [{"name": "afriend"}] if plugin else []},
        "cases": entries,
    }
    (results / "aggregate-result.json").write_text(json.dumps(payload), encoding="utf-8")
    return results


def test_the_expected_skill_map_covers_every_positive_case():
    """A case absent from the map is silently unchecked, which is the state
    this script exists to leave behind."""
    expected = json.loads((EVALS / "expectations.json").read_text(encoding="utf-8"))["cases"]
    positives = {
        path.name for path in EVALS.iterdir() if path.is_dir() and path.name.startswith("pos-")
    }
    assert positives == set(expected), positives.symmetric_difference(set(expected))
    assert set(expected.values()) <= {
        "afriend:review",
        "afriend:status",
        "afriend:configure",
        "afriend:resolve",
    }


def test_a_correct_selection_passes(tmp_path):
    results = _run(tmp_path, {"pos-afriend-resume-run-123": ("afriend:review",)})
    assert _module().check(results) == 0


def test_the_wrong_skill_is_rejected(tmp_path):
    """The exact case the harness cannot catch: `afriend resume run-123`
    routed to claim resolution instead of run resumption."""
    results = _run(tmp_path, {"pos-afriend-resume-run-123": ("afriend:resolve",)})
    assert _module().check(results) == 1


def test_a_trace_with_no_skill_at_all_is_rejected(tmp_path):
    results = _run(tmp_path, {"pos-afriend-status": ()})
    assert _module().check(results) == 1


def test_an_empty_directory_reports_nothing_to_check_rather_than_success(tmp_path):
    """The failure mode that matters most. A checker that returns 0 when it
    found no traces is indistinguishable from one that verified them, and
    would have made every future run report a pass it never observed."""
    assert _module().check(tmp_path) == 2


def test_a_run_that_loaded_no_plugin_is_refused_rather_than_failed(tmp_path):
    """The real defect this caught: targeting the suite directory instead of
    the plugin runs every case with no afriend skill available. Each one then
    fires nothing, which is a true statement about a meaningless run -- so it
    must report "cannot check", not "wrong skill"."""
    results = _run(tmp_path, {"pos-afriend-status": ()}, plugin=False)
    assert _module().check(results) == 2


def test_a_case_whose_trace_was_not_kept_is_not_counted_as_checked(tmp_path):
    """Without --keep-temp the transcripts are deleted. Scoring that as a
    pass would report verification of something never read."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    payload = json.loads((results / "aggregate-result.json").read_text(encoding="utf-8"))
    Path(payload["cases"][0]["arms"]["with"][0]["tracePath"]).unlink()
    assert _module().check(results) == 2


def test_the_newest_run_is_chosen_when_pointed_at_the_results_parent(tmp_path):
    """`results/` accumulates one timestamped directory per run; checking a
    stale one would report on skills that are no longer shipped."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:review",)})
    newer = results.parent / "2026-06-01T00-00-00-000Z"
    newer.mkdir()
    trace = tmp_path / "newer-trace.jsonl"
    _write_trace(trace, "afriend:status")
    (newer / "aggregate-result.json").write_text(
        json.dumps(
            {
                "suite": {"plugins": [{"name": "afriend"}]},
                "cases": [
                    {
                        "name": "pos-afriend-status",
                        "arms": {"with": [{"tracePath": str(trace)}]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _module().check(results.parent) == 0


def test_the_ablation_baseline_arm_is_not_read_as_evidence(tmp_path):
    """The `without` arm runs with no plugin by design, so its transcript can
    never contain an afriend skill; counting it would fail every case under
    the default ablation."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    path = results / "aggregate-result.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    baseline = tmp_path / "baseline.jsonl"
    _write_trace(baseline)
    payload["cases"][0]["arms"]["without"] = [{"tracePath": str(baseline)}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _module().check(results) == 0


def test_extra_skills_alongside_the_right_one_still_pass(tmp_path):
    """A run may legitimately consult more than one skill; the contract is
    that the expected one was among them."""
    results = _run(tmp_path, {"pos-afriend-status-run-123": ("afriend:review", "afriend:status")})
    assert _module().check(results) == 0


@pytest.mark.parametrize("case", ["pos-afriend-configure", "pos-afriend-resolve"])
def test_each_family_is_checked_against_its_own_expectation(tmp_path, case):
    expected = json.loads((EVALS / "expectations.json").read_text(encoding="utf-8"))["cases"]
    assert _module().check(_run(tmp_path / "ok", {case: (expected[case],)})) == 0
    other = "afriend:review" if expected[case] != "afriend:review" else "afriend:status"
    assert _module().check(_run(tmp_path / "bad", {case: (other,)})) == 1
