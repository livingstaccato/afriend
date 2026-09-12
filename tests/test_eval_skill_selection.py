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


def _expected_for(*cases: str) -> dict[str, str]:
    """The real expectation for each named case, and only those.

    `check()` refuses a run that leaves an expected case unverified, so a
    fixture exercising one case must say it expects one case -- otherwise the
    other twelve are correctly reported missing and every test measures that.
    """
    real = json.loads((EVALS / "expectations.json").read_text(encoding="utf-8"))["cases"]
    return {case: real[case] for case in cases}


def _check(target: Path, *cases: str) -> int:
    return _module().check(target, _expected_for(*cases))


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
    assert _check(results, "pos-afriend-resume-run-123") == 0


def test_the_wrong_skill_is_rejected(tmp_path):
    """The exact case the harness cannot catch: `afriend resume run-123`
    routed to claim resolution instead of run resumption."""
    results = _run(tmp_path, {"pos-afriend-resume-run-123": ("afriend:resolve",)})
    assert _check(results, "pos-afriend-resume-run-123") == 1


def test_a_trace_with_no_skill_at_all_is_rejected(tmp_path):
    results = _run(tmp_path, {"pos-afriend-status": ()})
    assert _check(results, "pos-afriend-status") == 1


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
    assert _check(results, "pos-afriend-status") == 2


def test_a_case_whose_trace_was_not_kept_is_not_counted_as_checked(tmp_path):
    """Without --keep-temp the transcripts are deleted. Scoring that as a
    pass would report verification of something never read."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    payload = json.loads((results / "aggregate-result.json").read_text(encoding="utf-8"))
    Path(payload["cases"][0]["arms"]["with"][0]["tracePath"]).unlink()
    assert _check(results, "pos-afriend-status") == 2


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
    assert _check(results.parent, "pos-afriend-status") == 0


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
    assert _check(results, "pos-afriend-status") == 0


def test_extra_skills_alongside_the_right_one_still_pass(tmp_path):
    """A run may legitimately consult more than one skill; the contract is
    that the expected one was among them."""
    results = _run(tmp_path, {"pos-afriend-status-run-123": ("afriend:review", "afriend:status")})
    assert _check(results, "pos-afriend-status-run-123") == 0


@pytest.mark.parametrize("case", ["pos-afriend-configure", "pos-afriend-resolve"])
def test_each_family_is_checked_against_its_own_expectation(tmp_path, case):
    expected = json.loads((EVALS / "expectations.json").read_text(encoding="utf-8"))["cases"]
    assert _check(_run(tmp_path / "ok", {case: (expected[case],)}), case) == 0
    other = "afriend:review" if expected[case] != "afriend:review" else "afriend:status"
    assert _check(_run(tmp_path / "bad", {case: (other,)}), case) == 1


def _payload(results: Path) -> dict:
    return json.loads((results / "aggregate-result.json").read_text(encoding="utf-8"))


def _save(results: Path, payload: dict) -> None:
    (results / "aggregate-result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_full_coverage_with_every_trace_kept_still_passes(tmp_path):
    """The guard on the guards below: refusing partial runs must not become
    refusing every run."""
    results = _run(
        tmp_path,
        {
            "pos-afriend-status": ("afriend:status",),
            "pos-afriend-resume-run-123": ("afriend:review",),
        },
    )
    assert _check(results, "pos-afriend-status", "pos-afriend-resume-run-123") == 0


def test_an_expected_case_the_run_never_executed_is_refused(tmp_path, capsys):
    """One passing case used to stand in for all of them.

    An absent case was skipped without even being counted, and the exit-2
    guard fired only when NOTHING was checked -- so a run that executed two
    of thirteen cases printed "all 2 checked case(s) selected the expected
    skill" and exited 0.
    """
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    assert _check(results, "pos-afriend-status", "pos-afriend-resume-run-123") == 2
    assert "pos-afriend-resume-run-123" in capsys.readouterr().err


def test_one_unkept_case_is_not_masked_by_one_checked_case(tmp_path, capsys):
    results = _run(
        tmp_path,
        {
            "pos-afriend-status": ("afriend:status",),
            "pos-afriend-resume-run-123": ("afriend:review",),
        },
    )
    payload = _payload(results)
    Path(payload["cases"][1]["arms"]["with"][0]["tracePath"]).unlink()
    assert _check(results, "pos-afriend-status", "pos-afriend-resume-run-123") == 2
    assert "pos-afriend-resume-run-123" in capsys.readouterr().err


def test_a_case_missing_one_of_its_run_traces_is_refused(tmp_path):
    """Kept traces were filtered to the ones that exist, so a case declaring
    three runs was "checked" on whichever one survived."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    payload = _payload(results)
    payload["cases"][0]["arms"]["with"].append({"tracePath": str(tmp_path / "gone.jsonl")})
    _save(results, payload)
    assert _check(results, "pos-afriend-status") == 2


def test_one_correct_run_does_not_mask_a_wrong_one(tmp_path, capsys):
    """Every run's invocations were pooled before comparison.

    Under `--runs 3`, the resume case choosing `afriend:review` once and
    `afriend:status` twice -- the 0.11.0 regression, two times in three --
    passed, because the pooled list contained the right name.
    """
    results = _run(tmp_path, {"pos-afriend-resume-run-123": ("afriend:review",)})
    payload = _payload(results)
    wrong = tmp_path / "second-run.jsonl"
    _write_trace(wrong, "afriend:status")
    payload["cases"][0]["arms"]["with"].append({"tracePath": str(wrong)})
    _save(results, payload)
    assert _check(results, "pos-afriend-resume-run-123") == 1
    assert "run 2" in capsys.readouterr().err


def test_result_trees_at_different_depths_are_refused_as_ambiguous(tmp_path, capsys):
    """Whole paths were sorted, so the directory component beat the timestamp.

    Pointed one level too high, at a checkout holding both `evals/results/`
    and the mis-targeted `evals/evals/results/` the README names as the tell,
    `sorted(rglob)[-1]` picked by path order: `evals/results` sorts after
    `evals/evals` because "r" > "e", whatever either run's date.
    """
    evals = tmp_path / "evals"
    stale = _run(evals, {"pos-afriend-status": ("afriend:review",)})
    other = _run(evals / "evals", {"pos-afriend-status": ("afriend:status",)})
    assert _check(evals, "pos-afriend-status") == 2
    err = capsys.readouterr().err
    assert str(stale.parent) in err and str(other.parent) in err


def test_a_missing_suite_object_is_a_schema_mismatch_not_a_wrong_target(tmp_path, capsys):
    """An absent key and an empty value gave the same advice.

    With no `suite` at all the user was told to re-target the plugin
    directory -- specific, confident, and wrong, sending them to rerun an
    eval they had already pointed at the right place.
    """
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    payload = _payload(results)
    del payload["suite"]
    _save(results, payload)
    assert _check(results, "pos-afriend-status") == 2
    err = capsys.readouterr().err
    assert "schema" in err
    assert "plugin directory" not in err


def test_a_renamed_arms_key_is_a_schema_mismatch_not_unkept_traces(tmp_path, capsys):
    """Any shape mismatch in a case landed in `unkept`, whose message says
    the traces are gone and to rerun with `--keep-temp` -- a paid rerun of a
    suite that kept every trace it was asked to."""
    results = _run(tmp_path, {"pos-afriend-status": ("afriend:status",)})
    payload = _payload(results)
    payload["cases"][0]["runs"] = payload["cases"][0].pop("arms")
    _save(results, payload)
    assert _check(results, "pos-afriend-status") == 2
    err = capsys.readouterr().err
    assert "schema" in err
    assert "--keep-temp" not in err


REAL = Path(__file__).resolve().parent / "fixtures" / "eval_skill_selection_real"


def _real_run(tmp_path: Path) -> tuple[Path, dict]:
    """The committed real result, with its trace placeholders pointed at the fixture."""
    payload = json.loads((REAL / "aggregate-result.json").read_text(encoding="utf-8"))
    for case in payload["cases"]:
        for run in case["arms"]["with"]:
            run["tracePath"] = run["tracePath"].replace("<fixtures>", str(REAL))
    results = tmp_path / "results" / "2026-09-12T20-19-43-000Z"
    results.mkdir(parents=True)
    _save(results, payload)
    return results, payload


def test_the_checker_reads_real_claude_plugin_eval_output(tmp_path):
    """Every other fixture here shares one assumed schema.

    This one is real output from `claude plugin eval plugins/afriend --runs 2
    --keep-temp`: thirteen expected cases, two runs each, paths redacted and
    each trace cut to its `Skill` record. If the harness renames `arms`,
    `tracePath` or `suite.plugins`, this is the test that says so -- before a
    user is told their correctly-targeted eval was aimed at the wrong place.
    """
    results, _ = _real_run(tmp_path)
    assert _module().check(results) == 0


def test_a_real_trace_naming_the_wrong_skill_is_rejected(tmp_path):
    """Proof the real traces are actually read, not merely present: the same
    real record with its skill changed must fail the case it belongs to."""
    results, payload = _real_run(tmp_path)
    case = next(c for c in payload["cases"] if c["name"] == "pos-afriend-resume-run-123")
    original = Path(case["arms"]["with"][0]["tracePath"])
    wrong = tmp_path / "wrong-trace.jsonl"
    wrong.write_text(
        original.read_text(encoding="utf-8").replace('"afriend:review"', '"afriend:status"'),
        encoding="utf-8",
    )
    assert wrong.read_text(encoding="utf-8") != original.read_text(encoding="utf-8")
    case["arms"]["with"][0]["tracePath"] = str(wrong)
    _save(results, payload)
    assert _module().check(results) == 1
