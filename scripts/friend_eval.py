#!/usr/bin/env python3
"""Score a live afriend run against a review whose findings are already known.

The activation evals ask whether a host selects the right skill. This asks
whether the friends find real defects, by replaying a review that already
happened: revision 2 of this repository's design spec was reviewed by
independent friends, and revision 3's section 19 records every finding and how
it was settled. That record is evals/friends/ground-truth.json -- 21 review
findings, and 13 items of v2's own backlog that v3 folded in.

    scripts/friend_eval.py artifact --out /tmp/friend-eval/spec-v2.md
    <run the afriend command it prints>
    scripts/friend_eval.py score /tmp/friend-eval/runs --method 3

The artifact must sit outside any git repository. Inside this checkout the
friends would get repository scope, and the repository holds revision 3: the
answers.

Every claim the run left standing, or rejected, lands in one class:

- matched: it names a ground-truth finding. Two claims naming one finding are
  both matched; the finding is recalled once.
- new-plausible: it names no known finding and is worth a person's look.
- noise: it names no known finding and is not.

Recall is reported separately for review findings and folded-in items, because
no reviewer raised the folded-in backlog; count it in or out as the question
requires. A claim the run superseded is scored through its successor.

Three methods, chosen with --method:

1. An LLM judge. `judge` sends the ground truth and the claims to --judge-cmd
   and writes the mapping it returns, plus a seeded sample of claims for a
   person to confirm. `score --method 1` refuses until each is confirmed.
2. A person. `template` writes a mapping to fill in; `score --method 2` reads it.
3. A keyword heuristic that `score --method 3` computes itself: a claim's text
   and location match the finding whose keywords they share most, past a
   threshold, and an
   unmatched claim is noise exactly when the run discarded or refuted it.
   Repeatable and free, and wrong often enough to be a smoke test only.

Exit codes for `score`: 0 scored; 1 the spot-check found the judge wrong; 2 the
run or mapping cannot be scored -- an unreadable run, a mapping that misses or
invents a claim or names an unknown finding, or a spot-check not yet confirmed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import re
import shlex
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
FRIEND_EVAL = REPO / "evals" / "friends"
GROUND_TRUTH = FRIEND_EVAL / "ground-truth.json"
PROVENANCE = FRIEND_EVAL / "provenance.json"
# The roster the ground truth's review used, one lens per provider family.
ROSTER = ("codex:spec-vs-reality", "agy:security", "claude:assumptions")
EXTERNAL_TOOLS = "agy"
CLASSES = ("matched", "new-plausible", "noise")
CATEGORIES = ("review-finding", "folded-in")
METHODS = (1, 2, 3)
SUPERSEDED = "superseded"
REJECTED_STATES = frozenset({"discarded", "settled-refuted"})
JUDGE_TIMEOUT_S = 900
DEFAULT_SPOT_CHECK = 3
DEFAULT_SEED = 0
# Method 3: the share of a finding's keywords a claim must contain to match it.
MATCH_THRESHOLD = 0.5
MIN_WORD = 4
STOPWORDS = frozenset(
    {
        "about", "after", "also", "because", "been", "before", "being", "cannot",
        "claim", "claims", "could", "does", "each", "every", "from", "have", "into",
        "must", "never", "only", "other", "same", "should", "than", "that", "their",
        "them", "then", "there", "they", "this", "under", "what", "when", "where",
        "which", "while", "will", "with", "would",
    }
)  # fmt: skip


class Unreadable(Exception):
    """The run or mapping cannot be scored, for a reason worded so a user can act on it."""


@dataclass(frozen=True)
class Finding:
    id: str
    finding: str
    change: str
    category: str


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    location: str
    detail: str
    state: str


Labels = dict[str, tuple[str, str | None]]


def load_ground_truth(path: Path = GROUND_TRUTH) -> list[Finding]:
    data = json.loads(path.read_text(encoding="utf-8"))
    findings = [
        Finding(entry["id"], entry["finding"], entry["v3_change"], entry["category"])
        for entry in data["findings"]
    ]
    unknown = sorted({finding.category for finding in findings} - set(CATEGORIES))
    if unknown:
        raise Unreadable(f"{path} uses unknown categories: {', '.join(unknown)}")
    ids = [finding.id for finding in findings]
    if len(set(ids)) != len(ids):
        raise Unreadable(f"{path} repeats a finding id")
    return findings


def find_run(target: Path) -> Path:
    """The run directory a path refers to: the run itself, or `--out` holding exactly one."""
    if (target / "run.json").is_file():
        return target
    runs = sorted(path.parent for path in target.glob("*/run.json"))
    if len(runs) == 1:
        return runs[0]
    if runs:
        raise Unreadable(f"{target} holds {len(runs)} runs; point this at one of them")
    raise Unreadable(f"no run.json at or under {target}")


def load_run(target: Path) -> tuple[Path, list[Claim]]:
    run = find_run(target)
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    states = meta.get("claim_states")
    if not isinstance(states, dict) or not states:
        raise Unreadable(
            f"{run}/run.json records no claim states, so the run never judged its claims; "
            "run the eval in crossexam mode"
        )
    claims: list[Claim] = []
    for number, line in enumerate(
        (run / "claims.jsonl").read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Unreadable(f"{run}/claims.jsonl line {number} is not JSON: {exc}") from exc
        if record.get("type") != "claim":
            continue
        state = states.get(record["id"])
        if state is None:
            raise Unreadable(f"claim {record['id']} has no state in {run}/run.json")
        if state == SUPERSEDED:
            continue
        detail = " ".join(str(record.get(key) or "") for key in ("evidence", "failure_scenario"))
        claims.append(
            Claim(
                record["id"],
                str(record.get("claim") or ""),
                str(record.get("location") or ""),
                detail,
                state,
            )
        )
    if not claims:
        raise Unreadable(f"{run} holds no claims to score")
    return run, claims


def _stem(word: str) -> str:
    return word[:-1] if len(word) > MIN_WORD and word.endswith("s") else word


def keywords(text: str) -> set[str]:
    """Backticked terms whole, plus the remaining words of at least four letters."""
    lowered = text.lower()
    terms = {term.strip() for term in re.findall(r"`([^`]+)`", lowered) if term.strip()}
    rest = re.sub(r"`[^`]+`", " ", lowered)
    words = {
        _stem(word)
        for word in re.findall(r"[a-z0-9][a-z0-9-]*", rest)
        if len(word) >= MIN_WORD and word not in STOPWORDS
    }
    return terms | words


def heuristic(claims: Sequence[Claim], findings: Sequence[Finding]) -> Labels:
    wanted = {finding.id: keywords(finding.finding) for finding in findings}
    labels: Labels = {}
    for claim in claims:
        # The claim and its location only. Adding the evidence and failure scenario
        # tripled wrong matches on the two recorded runs (8 against a hand mapping
        # of 24 claims, versus none): longer text shares a short finding's words
        # by chance.
        text = f"{claim.text} {claim.location}"
        have = keywords(text)
        lowered = text.lower()
        best: str | None = None
        best_share = 0.0
        for finding in findings:
            want = wanted[finding.id]
            if not want:
                continue
            # A multi-word term counts when the claim uses it unquoted, too.
            hits = sum(1 for key in want if key in have or (" " in key and key in lowered))
            share = hits / len(want)
            if share > best_share:
                best, best_share = finding.id, share
        if best is not None and best_share >= MATCH_THRESHOLD:
            labels[claim.id] = ("matched", best)
        else:
            unmatched = "noise" if claim.state in REJECTED_STATES else "new-plausible"
            labels[claim.id] = (unmatched, None)
    return labels


def validate(
    mapping: object, claims: Sequence[Claim], findings: Sequence[Finding], method: int
) -> Labels:
    """The mapping's labels, or every reason it cannot be scored at once."""
    if not isinstance(mapping, dict):
        raise Unreadable("the mapping is not a JSON object")
    if mapping.get("method") != method:
        raise Unreadable(f"the mapping was made by method {mapping.get('method')}, not {method}")
    entries = mapping.get("claims")
    if not isinstance(entries, dict):
        raise Unreadable("the mapping has no `claims` object")
    ids = {claim.id for claim in claims}
    known = {finding.id for finding in findings}
    problems = [f"no label for {cid}" for cid in sorted(ids - set(entries))]
    problems += [f"{cid} is not a claim in this run" for cid in sorted(set(entries) - ids)]
    labels: Labels = {}
    for cid in sorted(ids & set(entries)):
        entry = entries[cid]
        label = entry.get("class") if isinstance(entry, dict) else None
        match = entry.get("match") if isinstance(entry, dict) else None
        if label not in CLASSES:
            problems.append(f"{cid}: class {label!r} is not one of {', '.join(CLASSES)}")
        elif label == "matched" and match not in known:
            problems.append(f"{cid}: matched to {match!r}, which is not a ground-truth finding")
        elif label != "matched" and match is not None:
            problems.append(f"{cid}: labelled {label} but names finding {match!r}")
        else:
            labels[cid] = (label, match)
    if problems:
        raise Unreadable("the mapping cannot be scored: " + "; ".join(problems))
    return labels


def summarize(labels: Labels, claims: Sequence[Claim], findings: Sequence[Finding]) -> dict:
    counts = dict.fromkeys(CLASSES, 0)
    for label, _ in labels.values():
        counts[label] += 1
    recalled = {match for label, match in labels.values() if label == "matched"}
    recall = {}
    for category in CATEGORIES:
        ids = [finding.id for finding in findings if finding.category == category]
        recall[category] = {
            "found": [fid for fid in ids if fid in recalled],
            "missed": [fid for fid in ids if fid not in recalled],
            "of": len(ids),
        }
    return {
        "claims": len(claims),
        "classes": counts,
        "recall": recall,
        "labels": {
            claim.id: {
                "class": labels[claim.id][0],
                "match": labels[claim.id][1],
                "state": claim.state,
            }
            for claim in claims
        },
    }


def judge_prompt(claims: Sequence[Claim], findings: Sequence[Finding]) -> str:
    known = [
        {"id": f.id, "finding": f.finding, "resolution": f.change, "category": f.category}
        for f in findings
    ]
    raised = [
        {
            "id": c.id,
            "claim": c.text,
            "location": c.location,
            "detail": c.detail,
            "run_state": c.state,
        }
        for c in claims
    ]
    return (
        "You are scoring a code-review run against findings already known for the same "
        "document.\n\nFor every claim, choose exactly one class:\n"
        '- "matched": the claim identifies the same defect as one known finding. Set "match" '
        "to that finding's id. Same defect, not merely the same section or topic.\n"
        '- "new-plausible": no known finding, and a careful reader would take it seriously.\n'
        '- "noise": no known finding, and it is wrong, trivial, or not a defect.\n\n'
        'Reply with only a JSON object: {"claims": {"<claim id>": {"class": "...", '
        '"match": "<finding id or null>", "note": "<one sentence>"}}}. Label every claim.\n\n'
        f"KNOWN FINDINGS:\n{json.dumps(known, indent=1)}\n\n"
        f"CLAIMS:\n{json.dumps(raised, indent=1)}\n"
    )


def _json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise Unreadable("the judge's output holds no JSON object")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise Unreadable(f"the judge's output is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise Unreadable("the judge's output is not a JSON object")
    return value


def run_judge(command: str, prompt: str) -> dict:
    words = shlex.split(command, posix=sys.platform != "win32")
    if not words:
        raise Unreadable("--judge-cmd is empty")
    # Windows parses a command line itself, and POSIX splitting would eat
    # every backslash in a Windows path; elsewhere the words are the argv.
    argv: str | list[str] = command if sys.platform == "win32" else words
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise Unreadable(f"judge command not found: {words[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise Unreadable(f"the judge did not answer within {JUDGE_TIMEOUT_S}s") from exc
    if proc.returncode != 0:
        raise Unreadable(f"the judge exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
    return _json_object(proc.stdout)


def spot_check_sample(claims: Sequence[Claim], size: int, seed: int) -> list[str]:
    ids = sorted(claim.id for claim in claims)
    return sorted(random.Random(seed).sample(ids, min(size, len(ids))))


def check_spot_check(mapping: Mapping[str, object], labels: Labels) -> list[str]:
    """Claims the person found the judge wrong about; refuses while any is unconfirmed."""
    sample = mapping.get("spot_check")
    if not isinstance(sample, dict) or not sample:
        raise Unreadable("the mapping has no spot_check sample; run `judge` to produce one")
    strangers = sorted(set(sample) - set(labels))
    if strangers:
        raise Unreadable(f"spot_check names claims not in this run: {', '.join(strangers)}")
    pending = sorted(cid for cid, verdict in sample.items() if verdict is None)
    if pending:
        raise Unreadable(
            f"spot-check not confirmed for {', '.join(pending)}: set each to true when the "
            "judge's label is right and false when it is wrong"
        )
    malformed = sorted(cid for cid, verdict in sample.items() if not isinstance(verdict, bool))
    if malformed:
        raise Unreadable(f"spot_check values must be true or false: {', '.join(malformed)}")
    return sorted(cid for cid, verdict in sample.items() if verdict is False)


def _inside_git_worktree(path: Path) -> bool:
    probe = path
    while not probe.exists():
        probe = probe.parent
    proc = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() == "true"


def materialize(out: Path) -> str:
    """Write revision 2 of the spec from git history, verified by digest."""
    if _inside_git_worktree(out.parent):
        raise Unreadable(
            f"{out} is inside a git repository, so friends would get repository scope; "
            "write the artifact outside any repository"
        )
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    ref = f"{provenance['source_commit']}:{provenance['path']}"
    proc = subprocess.run(["git", "-C", str(REPO), "show", ref], capture_output=True, check=False)
    if proc.returncode != 0:
        raise Unreadable(f"git cannot show {ref}; a shallow clone lacks it (git fetch --unshallow)")
    digest = hashlib.sha256(proc.stdout).hexdigest()
    if digest != provenance["sha256"]:
        raise Unreadable(f"{ref} hashes to {digest}, not the recorded {provenance['sha256']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(proc.stdout)
    return digest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_summary(run: Path, method: int, summary: dict, findings: Sequence[Finding]) -> None:
    names = {finding.id: finding.finding for finding in findings}
    classes = summary["classes"]
    print(f"run: {run} (method {method})")
    print(
        f"claims scored: {summary['claims']}  matched {classes['matched']}  "
        f"new-plausible {classes['new-plausible']}  noise {classes['noise']}"
    )
    for category in CATEGORIES:
        recall = summary["recall"][category]
        found = ", ".join(recall["found"]) or "none"
        print(f"{category} recall: {len(recall['found'])} of {recall['of']} ({found})")
    for cid, label in summary["labels"].items():
        match = f" {label['match']}  {names[label['match']]}" if label["match"] else ""
        print(f"  {cid:<10} {label['state']:<16} {label['class']}{match}")


def _artifact(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    digest = materialize(out)
    print(f"wrote {out} (sha256 {digest})", file=sys.stderr)
    friends = [part for friend in ROSTER for part in ("--friend", friend)]
    command = ["afriend", "run", str(out), "--mode", "crossexam", *friends]
    command += ["--fresh-host-worker", f"--allow-external-tools={EXTERNAL_TOOLS}"]
    print(shlex.join([*command, "--out", str(out.parent / "runs")]))
    return 0


def _template(args: argparse.Namespace) -> int:
    run, claims = load_run(args.run)
    findings = load_ground_truth()
    entries = {
        claim.id: {
            "class": None,
            "match": None,
            "note": "",
            "state": claim.state,
            "claim": claim.text,
        }
        for claim in claims
    }
    known = {finding.id: finding.finding for finding in findings}
    _write_json(args.out, {"method": 2, "run": str(run), "findings": known, "claims": entries})
    print(f"wrote {args.out}: label each of {len(claims)} claims, then score --method 2")
    return 0


def _judge(args: argparse.Namespace) -> int:
    run, claims = load_run(args.run)
    findings = load_ground_truth()
    answer = run_judge(args.judge_cmd, judge_prompt(claims, findings))
    mapping = {
        "method": 1,
        "run": str(run),
        "judge_cmd": args.judge_cmd,
        "claims": answer.get("claims"),
        "spot_check": dict.fromkeys(spot_check_sample(claims, args.spot_check, args.seed)),
    }
    _write_json(args.out, mapping)
    validate(mapping, claims, findings, 1)
    print(
        f"wrote {args.out}: confirm spot_check for {', '.join(mapping['spot_check'])}, "
        "then score --method 1"
    )
    return 0


def _score(args: argparse.Namespace) -> int:
    run, claims = load_run(args.run)
    findings = load_ground_truth()
    wrong: list[str] = []
    if args.method == 3:
        if args.mapping:
            raise Unreadable("method 3 computes its own labels; drop --mapping")
        labels = heuristic(claims, findings)
    else:
        if not args.mapping:
            raise Unreadable(f"method {args.method} reads its labels from --mapping")
        mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
        labels = validate(mapping, claims, findings, args.method)
        if args.method == 1:
            wrong = check_spot_check(mapping, labels)
    summary = summarize(labels, claims, findings)
    summary["method"] = args.method
    summary["spot_check_wrong"] = wrong
    _print_summary(run, args.method, summary, findings)
    if args.json:
        _write_json(args.json, summary)
    if wrong:
        print(
            f"the judge was wrong on {len(wrong)} spot-checked claim(s): {', '.join(wrong)}; "
            "its labels are not a score",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Score an afriend run against known findings.")
    commands = parser.add_subparsers(dest="command", required=True)
    artifact = commands.add_parser("artifact", help="write the spec under review from git")
    artifact.add_argument("--out", type=Path, required=True)
    template = commands.add_parser("template", help="write a mapping for a person (method 2)")
    template.add_argument("run", type=Path)
    template.add_argument("--out", type=Path, required=True)
    judge = commands.add_parser("judge", help="ask an LLM judge for a mapping (method 1)")
    judge.add_argument("run", type=Path)
    judge.add_argument("--judge-cmd", required=True, help="reads the prompt on stdin")
    judge.add_argument("--out", type=Path, required=True)
    judge.add_argument("--spot-check", type=int, default=DEFAULT_SPOT_CHECK)
    judge.add_argument("--seed", type=int, default=DEFAULT_SEED)
    score = commands.add_parser("score", help="score a run")
    score.add_argument("run", type=Path)
    score.add_argument("--method", type=int, choices=METHODS, required=True)
    score.add_argument("--mapping", type=Path)
    score.add_argument("--json", type=Path, help="also write the summary here")
    args = parser.parse_args(argv)
    handlers = {"artifact": _artifact, "template": _template, "judge": _judge, "score": _score}
    try:
        return handlers[args.command](args)
    except Unreadable as exc:
        print(f"error: {exc}.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
