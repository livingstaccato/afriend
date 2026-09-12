"""The friend eval's scorer, checked without a model call.

`scripts/friend_eval.py` scores a live afriend run against the findings
already known for revision 2 of the design spec. These exercise each scoring
method and every way a run or a mapping is refused, against two real crossexam
runs of that artifact (claim records and final states only) and a fake judge.

`tests/fixtures/friend_eval_run_real/three-friends` is a codex, agy and fresh
claude run; `codex-agy-superseded` is a two-friend run in which one claim was
amended, so its first version is superseded.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
REAL = REPO / "tests" / "fixtures" / "friend_eval_run_real"
THREE = REAL / "three-friends"
SUPERSEDED = REAL / "codex-agy-superseded"


def _module():
    path = REPO / "scripts" / "friend_eval.py"
    spec = importlib.util.spec_from_file_location("friend_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _module()
FINDINGS = M.load_ground_truth()


def _claim(cid, text, state="settled-upheld"):
    return M.Claim(cid, text, "", "", state)


def _run(tmp_path, claims, states):
    run = tmp_path / "run"
    run.mkdir()
    run.joinpath("claims.jsonl").write_text("".join(json.dumps(c) + "\n" for c in claims))
    run.joinpath("run.json").write_text(json.dumps({"claim_states": states}))
    return run


def test_the_ground_truth_holds_21_review_findings_and_13_folded_in():
    categories = [finding.category for finding in FINDINGS]

    assert categories.count("review-finding") == 21
    assert categories.count("folded-in") == 13


def test_a_superseded_claim_is_scored_through_its_successor():
    _, claims = M.load_run(SUPERSEDED)
    ids = [claim.id for claim in claims]

    assert "c-0006@1" not in ids
    assert "c-0006@2" in ids
    assert len(ids) == 8


def test_an_out_directory_holding_one_run_is_accepted_and_two_are_refused(tmp_path):
    single = tmp_path / "single"
    (single / "run-a").mkdir(parents=True)
    (single / "run-a" / "run.json").write_text("{}")
    assert M.find_run(single) == single / "run-a"

    (single / "run-b").mkdir()
    (single / "run-b" / "run.json").write_text("{}")
    with pytest.raises(M.Unreadable, match="holds 2 runs"):
        M.find_run(single)


def test_a_run_that_never_judged_is_refused(tmp_path):
    run = _run(tmp_path, [{"type": "claim", "id": "c-1", "claim": "x"}], {})

    with pytest.raises(M.Unreadable, match="crossexam"):
        M.load_run(run)


def test_a_claim_with_no_recorded_state_is_refused(tmp_path):
    claims = [{"type": "claim", "id": "c-1", "claim": "x"}, {"type": "claim", "id": "c-2"}]
    run = _run(tmp_path, claims, {"c-1": "settled-upheld"})

    with pytest.raises(M.Unreadable, match="c-2 has no state"):
        M.load_run(run)


def test_the_heuristic_matches_by_keyword_and_classes_the_rest_by_run_state():
    claims = [
        _claim("c-1", "The `settled-refuted` state is unreachable as defined."),
        _claim("c-2", "The logo colours are inconsistent.", "discarded"),
        _claim("c-3", "The logo colours are inconsistent.", "deadlocked"),
        # Two of H2's five keywords: related, and below the threshold.
        _claim("c-4", "Some flags are ordinary.", "deadlocked"),
    ]

    assert M.heuristic(claims, FINDINGS) == {
        "c-1": ("matched", "H1"),
        "c-2": ("noise", None),
        "c-3": ("new-plausible", None),
        "c-4": ("new-plausible", None),
    }


def test_the_heuristic_finds_the_unreachable_state_in_a_real_run():
    _, claims = M.load_run(THREE)
    labels = M.heuristic(claims, FINDINGS)

    assert labels["c-0004@1"] == ("matched", "H1")


def _labels_mapping(claims, method=2, **overrides):
    entries = {claim.id: {"class": "noise", "match": None} for claim in claims}
    entries.update(overrides)
    return {"method": method, "claims": entries}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: m["claims"].pop("c-0001@1"), "no label for c-0001@1"),
        (lambda m: m["claims"].update({"c-9999@1": {"class": "noise"}}), "not a claim"),
        (lambda m: m["claims"].update({"c-0001@1": {"class": "matched", "match": "H99"}}), "H99"),
        (lambda m: m["claims"].update({"c-0001@1": {"class": "matched"}}), "None"),
        (lambda m: m["claims"].update({"c-0001@1": {"class": "noise", "match": "H1"}}), "names"),
        (lambda m: m["claims"].update({"c-0001@1": {"class": None}}), "is not one of"),
        (lambda m: m.update({"method": 1}), "method 1, not 2"),
    ],
)
def test_a_mapping_that_cannot_be_scored_is_refused(change, message):
    _, claims = M.load_run(THREE)
    mapping = _labels_mapping(claims)
    change(mapping)

    with pytest.raises(M.Unreadable, match=message):
        M.validate(mapping, claims, FINDINGS, 2)


def test_recall_counts_a_finding_once_and_reports_folded_in_separately():
    claims = [_claim("c-1", "a"), _claim("c-2", "b"), _claim("c-3", "c")]
    labels = {
        "c-1": ("matched", "H1"),
        "c-2": ("matched", "H1"),
        "c-3": ("matched", "folded-9"),
    }
    summary = M.summarize(labels, claims, FINDINGS)

    assert summary["classes"] == {"matched": 3, "new-plausible": 0, "noise": 0}
    assert summary["recall"]["review-finding"]["found"] == ["H1"]
    assert summary["recall"]["review-finding"]["of"] == 21
    assert summary["recall"]["folded-in"]["found"] == ["folded-9"]
    assert summary["recall"]["folded-in"]["of"] == 13


def test_a_filled_template_scores_by_method_2(tmp_path, capsys):
    mapping_path = tmp_path / "mapping.json"
    assert M.main(["template", str(THREE), "--out", str(mapping_path)]) == 0
    assert M.main(["score", str(THREE), "--method", "2", "--mapping", str(mapping_path)]) == 2

    mapping = json.loads(mapping_path.read_text())
    for cid, entry in mapping["claims"].items():
        entry["class"] = "matched" if cid == "c-0004@1" else "noise"
        entry["match"] = "H1" if cid == "c-0004@1" else None
    mapping_path.write_text(json.dumps(mapping))
    summary_path = tmp_path / "summary.json"
    capsys.readouterr()

    argv = ["score", str(THREE), "--method", "2", "--mapping", str(mapping_path)]
    assert M.main([*argv, "--json", str(summary_path)]) == 0
    summary = json.loads(summary_path.read_text())
    assert summary["classes"] == {"matched": 1, "new-plausible": 0, "noise": 15}
    assert "review-finding recall: 1 of 21 (H1)" in capsys.readouterr().out


def _fake_judge(tmp_path, body):
    script = tmp_path / "judge.py"
    script.write_text(body)
    return f"{sys.executable} {script}"


LABEL_EVERYTHING = """
import json, re, sys
prompt = sys.stdin.read()
ids = sorted(set(re.findall(r'"id": "(c-[0-9]+@[0-9]+)"', prompt)))
labels = {cid: {"class": "noise", "match": None, "note": ""} for cid in ids}
labels["c-0004@1"] = {"class": "matched", "match": "H1", "note": "same defect"}
print("Here is the mapping:\\n```json\\n" + json.dumps({"claims": labels}) + "\\n```")
"""


def test_method_1_refuses_until_a_person_confirms_the_spot_check(tmp_path, capsys):
    mapping_path = tmp_path / "judged.json"
    judge = _fake_judge(tmp_path, LABEL_EVERYTHING)
    argv = ["judge", str(THREE), "--judge-cmd", judge, "--out", str(mapping_path)]
    assert M.main(argv) == 0

    mapping = json.loads(mapping_path.read_text())
    assert len(mapping["spot_check"]) == 3
    score = ["score", str(THREE), "--method", "1", "--mapping", str(mapping_path)]
    capsys.readouterr()
    assert M.main(score) == 2
    assert "spot-check not confirmed" in capsys.readouterr().err

    mapping["spot_check"] = dict.fromkeys(mapping["spot_check"], True)
    mapping_path.write_text(json.dumps(mapping))
    assert M.main(score) == 0

    first = next(iter(mapping["spot_check"]))
    mapping["spot_check"][first] = False
    mapping_path.write_text(json.dumps(mapping))
    assert M.main(score) == 1


def test_the_spot_check_sample_is_repeatable_for_a_seed():
    _, claims = M.load_run(THREE)

    assert M.spot_check_sample(claims, 3, 7) == M.spot_check_sample(claims, 3, 7)
    assert len(M.spot_check_sample(claims, 99, 0)) == len(claims)


def test_a_judge_that_answers_without_json_is_refused(tmp_path, capsys):
    judge = _fake_judge(tmp_path, "print('I think most of these are fine.')\n")
    argv = ["judge", str(THREE), "--judge-cmd", judge, "--out", str(tmp_path / "m.json")]

    assert M.main(argv) == 2
    assert "holds no JSON object" in capsys.readouterr().err


def test_the_judge_prompt_names_every_claim_and_finding():
    _, claims = M.load_run(THREE)
    prompt = M.judge_prompt(claims, FINDINGS)

    assert all(f'"id": "{claim.id}"' in prompt for claim in claims)
    assert all(f'"id": "{finding.id}"' in prompt for finding in FINDINGS)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--method", "3", "--mapping", "x.json"], "drop --mapping"),
        (["--method", "1"], "reads its labels from --mapping"),
    ],
)
def test_a_method_given_the_wrong_input_is_refused(argv, message, capsys):
    assert M.main(["score", str(THREE), *argv]) == 2
    assert message in capsys.readouterr().err


def test_the_artifact_is_refused_inside_a_git_repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    with pytest.raises(M.Unreadable, match="repository scope"):
        M.materialize(tmp_path / "spec-v2.md")


def _history_has_the_artifact():
    provenance = json.loads(M.PROVENANCE.read_text())
    ref = f"{provenance['source_commit']}:{provenance['path']}"
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", ref]).returncode == 0


@pytest.mark.skipif(
    not _history_has_the_artifact(),
    reason="a shallow clone lacks the commit revision 2 of the spec comes from",
)
def test_the_artifact_is_rebuilt_from_git_with_its_recorded_digest(tmp_path, capsys):
    out = tmp_path / "friend-eval" / "spec-v2.md"

    assert M.main(["artifact", "--out", str(out)]) == 0
    provenance = json.loads(M.PROVENANCE.read_text())
    assert M.materialize(out) == provenance["sha256"]
    assert len(out.read_text().splitlines()) == provenance["lines"]
    command = capsys.readouterr().out
    assert "--mode crossexam" in command
    assert "--fresh-host-worker" in command


@pytest.mark.skipif(
    not _history_has_the_artifact(),
    reason="a shallow clone lacks the commit revision 2 of the spec comes from",
)
def test_an_artifact_that_no_longer_matches_its_digest_is_refused(tmp_path, monkeypatch):
    provenance = json.loads(M.PROVENANCE.read_text())
    provenance["sha256"] = "0" * 64
    tampered = tmp_path / "provenance.json"
    tampered.write_text(json.dumps(provenance))
    monkeypatch.setattr(M, "PROVENANCE", tampered)
    out = tmp_path / "out" / "spec-v2.md"

    with pytest.raises(M.Unreadable, match="not the recorded"):
        M.materialize(out)
    assert not out.exists()
