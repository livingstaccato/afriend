"""The assertion `claude plugin eval` cannot make.

`tool_used` accepts only a tool name, so every positive activation case is
graded on "some Skill fired". A prompt that wrongly routed `afriend resume
run-123` to `afriend:resolve` instead of `afriend:review` scored exactly the
same as the correct selection. `scripts/check_eval_skill_selection.py` adds
the missing check, and these exercise its rejection behaviour against
synthetic traces so it costs nothing to verify -- a checker whose failure
path has never run is the thing it exists to prevent.
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


def _trace(tmp_path: Path, case: str, *skills: str) -> Path:
    case_dir = tmp_path / case
    case_dir.mkdir(parents=True, exist_ok=True)
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
    path = case_dir / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


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
    _trace(tmp_path, "pos-afriend-resume-run-123", "afriend:review")
    assert _module().check(tmp_path) == 0


def test_the_wrong_skill_is_rejected(tmp_path):
    """The exact case the harness cannot catch: `afriend resume run-123`
    routed to claim resolution instead of run resumption."""
    _trace(tmp_path, "pos-afriend-resume-run-123", "afriend:resolve")
    assert _module().check(tmp_path) == 1


def test_a_trace_with_no_skill_at_all_is_rejected(tmp_path):
    _trace(tmp_path, "pos-afriend-status")
    assert _module().check(tmp_path) == 1


def test_an_empty_directory_reports_nothing_to_check_rather_than_success(tmp_path):
    """The failure mode that matters most. A checker that returns 0 when it
    found no traces is indistinguishable from one that verified them, and
    would have made every future run report a pass it never observed."""
    assert _module().check(tmp_path) == 2


def test_extra_skills_alongside_the_right_one_still_pass(tmp_path):
    """A run may legitimately consult more than one skill; the contract is
    that the expected one was among them."""
    _trace(tmp_path, "pos-afriend-status-run-123", "afriend:review", "afriend:status")
    assert _module().check(tmp_path) == 0


@pytest.mark.parametrize("case", ["pos-afriend-configure", "pos-afriend-resolve"])
def test_each_family_is_checked_against_its_own_expectation(tmp_path, case):
    expected = json.loads((EVALS / "expectations.json").read_text(encoding="utf-8"))["cases"]
    _trace(tmp_path, case, expected[case])
    assert _module().check(tmp_path) == 0
    other = "afriend:review" if expected[case] != "afriend:review" else "afriend:status"
    _trace(tmp_path, case, other)
    assert _module().check(tmp_path) == 1
