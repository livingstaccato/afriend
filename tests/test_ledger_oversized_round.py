"""One oversized claim must cost one claim, not the whole round."""

import json

from e2e_helpers import run_af


def _run_dir(tmp_path):
    return sorted((tmp_path / "runs").iterdir())[0]


def test_an_oversized_claim_is_dropped_and_the_round_still_reports(tmp_path):
    """`commands/critique.py` appended every incoming claim in a bare `for`
    loop with no handler, so `Ledger.append` refusing one oversized record
    raised UsageError -> AfError straight past `finish_run`. The run
    directory then held no run.json and no report.md, every other friend's
    answers for the round went unreported, and `--resume` could not restore
    it because restore needs run.json. A friend may print up to
    MAX_OUTPUT_BYTES (32 MiB) against an 8 MiB ledger line cap, so this is
    reachable from verbosity alone.
    """
    artifact = tmp_path / "spec.md"
    artifact.write_text("# spec\n\nSome design text.\n")

    result = run_af(
        tmp_path,
        artifact,
        "--friend",
        "fake:oversized_claim",
        "--friend",
        "fake:good",
    )

    run_dir = _run_dir(tmp_path)
    assert (run_dir / "run.json").is_file(), result.stdout + result.stderr
    assert (run_dir / "report.md").is_file()

    meta = json.loads((run_dir / "run.json").read_text())
    downgrades = " ".join(meta.get("downgrades", []))
    assert "was dropped and is not in the ledger" in downgrades, downgrades
    assert "line limit" in downgrades

    ledger = [
        json.loads(line)
        for line in (run_dir / "claims.jsonl").read_text().splitlines()
        if line.strip()
    ]
    claims = [r for r in ledger if r.get("type") == "claim"]
    texts = [c["claim"] for c in claims]
    assert any("the second finding must survive the first" in t for t in texts), texts
    assert any("the guard is missing" in t for t in texts), texts
    assert not any(len(t) > 1_000_000 for t in texts)
