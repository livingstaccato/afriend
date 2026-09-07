"""Write one durable, non-mutating implementation proposal for a terminal run."""

import argparse
import os
from pathlib import Path

from ..errors import UsageError
from ..secureio import secure_create_bytes, secure_open_directory, secure_regular_exists
from . import status


def _code(value: str) -> str:
    """Render a path or identifier as one conservative Markdown code span."""
    rendered = value.replace("`", "'").replace("\n", " ").replace("\r", " ")
    return f"`{rendered}`"


def _proposal_inputs(
    summary: dict[str, object], *, root: Path
) -> tuple[str, str, list[dict[str, object]]]:
    """Validate the small safe status projection this command needs.

    ``status.summarize`` is intentionally permissive enough to inspect old or
    incomplete runs. A durable proposal needs a complete terminal record so
    its linked inputs can be audited later.
    """
    triage = summary.get("triage")
    if not isinstance(triage, dict):
        raise UsageError("run status has no valid triage projection")
    report_path = triage.get("report_path")
    ledger_path = triage.get("ledger_path")
    if not isinstance(report_path, str) or not isinstance(ledger_path, str):
        raise UsageError("terminal run is incomplete: report.md and claims.jsonl are required")
    unresolved = triage.get("unresolved_claim_ids")
    findings = triage.get("final_findings")
    count = triage.get("unresolved_count")
    if (
        not isinstance(unresolved, list)
        or not all(isinstance(claim_id, str) for claim_id in unresolved)
        or len(set(unresolved)) != len(unresolved)
        or type(count) is not int
        or count != len(unresolved)
        or not isinstance(findings, list)
    ):
        raise UsageError("run status has malformed unresolved-claim triage")
    by_id: dict[str, dict[str, object]] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            raise UsageError("run status has malformed final-findings triage")
        claim_id = finding.get("id")
        severity = finding.get("severity")
        paths = finding.get("evidence_paths")
        if (
            not isinstance(claim_id, str)
            or not isinstance(severity, str)
            or not isinstance(paths, list)
            or not all(isinstance(path, str) for path in paths)
            or claim_id in by_id
        ):
            raise UsageError("run status has malformed final-findings triage")
        by_id[claim_id] = finding
    selected: list[dict[str, object]] = []
    for claim_id in unresolved:
        try:
            finding = by_id[claim_id]
        except KeyError as exc:
            raise UsageError("run status triage names an unknown unresolved claim") from exc
        paths = finding["evidence_paths"]
        assert isinstance(paths, list)
        safe_paths: list[str] = []
        for path in paths:
            assert isinstance(path, str)
            try:
                if secure_regular_exists(Path(path), root=root):
                    safe_paths.append(path)
            except OSError as exc:
                raise UsageError(
                    f"unresolved claim {claim_id} has an unsafe parsed-evidence path"
                ) from exc
        if not safe_paths:
            raise UsageError(
                f"terminal run is incomplete: unresolved claim {claim_id} has no safe parsed evidence"
            )
        selected.append(
            {
                "id": claim_id,
                "severity": finding["severity"],
                "evidence_paths": safe_paths,
            }
        )
    return report_path, ledger_path, sorted(selected, key=lambda finding: str(finding["id"]))


def _render(run_dir: Path, summary: dict[str, object], *, root: Path) -> str:
    report_path, ledger_path, findings = _proposal_inputs(summary, root=root)
    lines = [
        "# Proposal — review before implementation",
        "",
        "This proposal is non-mutating. Review it before implementation; it does not dispatch "
        "friends, edit repository code, change run metadata or the review ledger, resolve claims, "
        "or verify fixes.",
        "",
        "## Source",
        "",
        f"Source run: {_code(run_dir.name)}",
        f"Ledger: {_code(ledger_path)}",
        f"Report: {_code(report_path)}",
        "",
        "## Claim-linked checklist",
        "",
    ]
    if not findings:
        lines.append("No unresolved canonical claims were recorded.")
    for finding in findings:
        claim_id = finding["id"]
        severity = finding["severity"]
        paths = finding["evidence_paths"]
        assert isinstance(claim_id, str)
        assert isinstance(severity, str)
        assert isinstance(paths, list)
        assert paths
        lines.append(f"- [ ] {_code(claim_id)} (severity: {severity})")
        lines.append("  - Evidence:")
        for path in paths:
            assert isinstance(path, str)
            lines.append(f"    - {_code(path)}")
    lines.extend(
        [
            "",
            "## Review boundary",
            "",
            "Use the linked report, ledger, and parsed evidence artifacts to decide what to implement. "
            "This file is a proposal, not a resolution or verification record.",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_plan(args: argparse.Namespace) -> int:
    """Create ``PLAN.md`` once for a complete, terminal persisted run."""
    run_dir, root = status.find_run(args.run_id, getattr(args, "out", None))
    meta = status._read_json(run_dir / "run.json", root=root, label="saved run metadata")
    if meta.get("lifecycle_state") != "terminal":
        raise UsageError("can only create a proposal for terminal persisted run metadata")
    summary = status.summarize(run_dir, root=root)
    if summary.get("state") != "terminal":
        raise UsageError("can only create a proposal for a terminal run")
    proposal = _render(run_dir, summary, root=root).encode("utf-8")
    target = run_dir / "PLAN.md"
    try:
        secure_create_bytes(target, proposal, root=root)
    except FileExistsError as exc:
        raise UsageError(f"{target} already exists; refusing to replace proposal history") from exc
    except OSError as exc:
        raise UsageError(f"cannot create proposal {target}: {exc}") from exc
    try:
        directory = secure_open_directory(run_dir, root=root)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise UsageError(
            f"proposal was created but its directory could not be synced: {exc}"
        ) from exc
    print(target)
    return 0
