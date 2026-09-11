"""Read-only inspection and bounded watching of persisted runs."""

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from ..errors import UsageError
from ..events import EventRecord, read_events
from ..ids import FRIEND_NAME_RE
from ..jsonio import MAX_JSON_FILE_BYTES, decode_json_object
from ..ledger import Alias, Claim, Resolution, record_from_dict
from ..reviewcompleteness import from_friends
from ..runstore import default_root
from ..secureio import secure_open_directory, secure_read_bytes, secure_regular_exists
from ..verdicts import CONTESTED, INCOMPLETE, SETTLED_REFUTED, TERMINAL_STATES, UNPROVEN

STATUS_SCHEMA_VERSION = 4
_POLL_S = 0.25
_MAX_LEDGER_BYTES = 128 * 1024 * 1024
_CLAIM_STATES = TERMINAL_STATES | {CONTESTED, UNPROVEN, INCOMPLETE}


def _as_root(value: str | None) -> Path:
    """Return the caller-selected root, resolved the way the writer reaches it.

    `afriend run --out <symlink>` writes through the symlink and prints the
    resolved run path; opening the same root here with secure_open_directory's
    O_NOFOLLOW then failed with `[Errno 20] Not a directory` -- naming a path
    that IS a directory -- so status, --json and --watch were unusable for
    anyone whose --out or ~/.local/state is a link to another volume. The
    reader must reach the root the writer reached. O_NOFOLLOW still guards
    every component BELOW the root, which is where a swapped path would
    matter; the root is the operator's own argument.
    """
    return (Path(value) if value else default_root()).resolve()


def _open_directory(path: Path, *, root: Path) -> None:
    try:
        descriptor = secure_open_directory(path, root=root)
    except OSError as exc:
        raise UsageError(f"cannot inspect run directory {path}: {exc}") from exc
    os.close(descriptor)


def find_run(run_id_or_path: str, out: str | None) -> tuple[Path, Path]:
    """Find a run without accepting paths outside the selected run root."""
    root = _as_root(out)
    try:
        _open_directory(root, root=root)
    except UsageError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise UsageError(
                f"no such run: {run_id_or_path!r} (run root {root} does not exist)"
            ) from exc
        raise
    supplied = Path(run_id_or_path)
    if supplied.is_absolute() or len(supplied.parts) != 1 or supplied.name in {"", ".", ".."}:
        # Resolved for the same reason as the root: the absolute path the user
        # pastes back is the one `afriend run` printed, which is already
        # resolved, and the containment check below compares it to a resolved
        # root.
        candidate = supplied.resolve()
    else:
        candidate = root / supplied.name
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UsageError(f"run path {candidate} is outside the run root {root}") from exc
    try:
        _open_directory(candidate, root=root)
    except UsageError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise UsageError(
                f"no such run: {run_id_or_path!r} (looked in {root}). Pass the run directory "
                "that afriend run printed, or --out if it was written elsewhere."
            ) from exc
        raise
    return candidate, root


def _read_json(path: Path, *, root: Path, label: str) -> dict[str, Any]:
    try:
        payload = secure_read_bytes(path, root=root, max_bytes=MAX_JSON_FILE_BYTES)
    except FileNotFoundError as exc:
        raise UsageError(f"{path.parent} is not a run directory: no {path.name}") from exc
    except OSError as exc:
        raise UsageError(f"cannot read {label} {path}: {exc}") from exc
    return decode_json_object(payload, path=path, label=label)


def _read_optional_json(path: Path, *, root: Path, label: str) -> tuple[dict[str, Any], bool]:
    """A run can expose events before its initial metadata checkpoint."""
    try:
        return _read_json(path, root=root, label=label), True
    except UsageError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return {}, False
        raise


def _read_events(path: Path, *, root: Path) -> list[EventRecord]:
    """Keep unreadable telemetry in the command's normal error boundary."""
    try:
        return read_events(path, root=root)
    except OSError as exc:
        raise UsageError(f"cannot read lifecycle events {path}: {exc}") from exc


def _read_ledger(path: Path, *, root: Path) -> list[Claim | Alias | Resolution]:
    """Read the ledger records status needs without constructing a Ledger.

    ``Ledger`` deliberately initializes its parent for writers, which is the
    wrong abstraction here: a status command must not chmod or create any
    caller-owned run artifact merely to inspect it.
    """
    try:
        payload = secure_read_bytes(path, root=root, max_bytes=_MAX_LEDGER_BYTES)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise UsageError(f"cannot read ledger {path}: {exc}") from exc
    records: list[Claim | Alias | Resolution] = []
    for line_no, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
            record = record_from_dict(parsed)
        except (json.JSONDecodeError, UsageError, TypeError, ValueError) as exc:
            raise UsageError(f"{path}:{line_no}: invalid ledger record: {exc}") from exc
        if isinstance(record, (Claim, Alias, Resolution)):
            records.append(record)
    return records


def _claim_counts(records: Iterable[Claim | Alias | Resolution]) -> dict[str, object]:
    claims: dict[str, Claim] = {}
    resolutions: dict[str, Resolution] = {}
    for record in records:
        if isinstance(record, Claim):
            claims[record.id] = record
        elif isinstance(record, Resolution):
            resolutions[record.claim_id] = record
    counts = Counter(
        resolutions[claim_id].disposition if claim_id in resolutions else "pending"
        for claim_id in claims
    )
    return {"total": len(claims), "by_status": dict(sorted(counts.items()))}


def _safe_regular_path(path: Path, *, root: Path) -> str | None:
    """Return a known regular artifact path without reading its contents."""
    try:
        return str(path) if secure_regular_exists(path, root=root) else None
    except OSError:
        return None


def _claim_states(meta: dict[str, Any]) -> dict[str, str]:
    """Return a complete validated persisted state map, or no state evidence.

    An old run has no claim-state checkpoint.  A malformed one is likewise
    not a source of triage conclusions, so status retains the conservative
    unresolved result instead of surfacing an invented state.
    """
    value = meta.get("claim_states")
    if type(value) is not dict or any(
        type(claim_id) is not str or type(state) is not str or state not in _CLAIM_STATES
        for claim_id, state in value.items()
    ):
        return {}
    return dict(value)


def _evidence_paths(
    meta: dict[str, Any], claims: Iterable[Claim], *, run_dir: Path, root: Path
) -> list[str]:
    """Project known parsed-result paths for claims' recorded origins.

    Claim text and evidence are untrusted prose, while raw output, prompts, and
    stderr are transcripts.  Neither belongs in status.  A frozen roster lets
    us map a ledger identity back to the corresponding parsed ``.json``
    artifact, if it exists, without opening any result content.
    """
    roster = meta.get("roster")
    if not isinstance(roster, list):
        return []
    paths: list[str] = []
    for claim in claims:
        for entry in roster:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            cli = entry.get("cli")
            lens = entry.get("lens")
            model = entry.get("model")
            effort = entry.get("effort")
            if (
                not isinstance(name, str)
                or FRIEND_NAME_RE.fullmatch(name) is None
                or not isinstance(cli, str)
                or FRIEND_NAME_RE.fullmatch(cli) is None
                or not isinstance(lens, str)
                or FRIEND_NAME_RE.fullmatch(lens) is None
                or (model is not None and not isinstance(model, str))
                or (effort is not None and not isinstance(effort, str))
            ):
                continue
            identity = f"{cli}/{lens}"
            if model:
                identity += f"@{model}"
            if effort:
                identity += f"+{effort}"
            # Older ledgers recorded the roster name rather than the current
            # cli/lens identity. Both are safe only after the roster name itself
            # has passed the path-name validation above.
            if identity not in claim.origin and name not in claim.origin:
                continue
            path = _safe_regular_path(run_dir / f"round-{claim.round}" / f"{name}.json", root=root)
            if path is not None and path not in paths:
                paths.append(path)
    return paths


def _contributing_claims(
    final_claim: Claim, claims: dict[str, Claim], aliases: Iterable[Alias]
) -> list[Claim]:
    """Recover every ledger claim whose parsed result supports a final finding.

    Both a duplicate alias and an amended successor preserve a relationship to
    an earlier claim, but each source claim's round remains authoritative for
    its result path.  Traverse those relationships backwards, then retain the
    append-only ledger order for stable presentation.
    """
    sources_by_target: dict[str, list[str]] = {}
    for claim in claims.values():
        if claim.supersedes is not None:
            sources_by_target.setdefault(claim.id, []).append(claim.supersedes)
    for alias in aliases:
        sources_by_target.setdefault(alias.canonical, []).append(alias.duplicate)

    contributing_ids: set[str] = set()

    def collect(claim_id: str) -> None:
        if claim_id in contributing_ids:
            return
        contributing_ids.add(claim_id)
        for source_id in sources_by_target.get(claim_id, []):
            if source_id in claims:
                collect(source_id)

    collect(final_claim.id)
    return [claim for claim_id, claim in claims.items() if claim_id in contributing_ids]


def _triage(
    records: Iterable[Claim | Alias | Resolution],
    meta: dict[str, Any],
    *,
    run_dir: Path,
    root: Path,
) -> dict[str, object]:
    """Build a transcript-safe final-findings projection from ledger metadata."""
    claims: dict[str, Claim] = {}
    aliased_ids: set[str] = set()
    aliases: list[Alias] = []
    superseded: set[str] = set()
    resolutions: dict[str, Resolution] = {}
    claim_states = _claim_states(meta)
    for record in records:
        if isinstance(record, Claim):
            claims[record.id] = record
            if record.supersedes is not None:
                superseded.add(record.supersedes)
        elif isinstance(record, Alias):
            aliased_ids.add(record.duplicate)
            aliases.append(record)
        else:
            resolutions[record.claim_id] = record

    final_claims = [
        claims[claim_id]
        for claim_id in sorted(claims)
        if claim_id not in aliased_ids and claim_id not in superseded
    ]
    findings: list[dict[str, object]] = []
    evidence_paths: list[str] = []
    unresolved_ids: list[str] = []
    for claim in final_claims:
        resolution = resolutions.get(claim.id)
        finding_paths = _evidence_paths(
            meta,
            _contributing_claims(claim, claims, aliases),
            run_dir=run_dir,
            root=root,
        )
        if resolution is None:
            finding_status = claim_states.get(claim.id, "unresolved")
            if finding_status != SETTLED_REFUTED:
                unresolved_ids.append(claim.id)
        else:
            finding_status = resolution.disposition
        findings.append(
            {
                "id": claim.id,
                "severity": claim.severity,
                "status": finding_status,
                "evidence_paths": finding_paths,
            }
        )
        for path in finding_paths:
            if path not in evidence_paths:
                evidence_paths.append(path)
    return {
        "final_claim_ids": [claim.id for claim in final_claims],
        "final_findings": findings,
        "unresolved_claim_ids": unresolved_ids,
        "unresolved_count": len(unresolved_ids),
        "report_path": _safe_regular_path(run_dir / "report.md", root=root),
        "ledger_path": _safe_regular_path(run_dir / "claims.jsonl", root=root),
        "evidence_paths": evidence_paths,
    }


def _roster_rows(meta: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Project only the fixed, safe roster fields into a status response."""
    roster = meta.get("roster")
    if not isinstance(roster, list):
        return {}
    rows: dict[str, dict[str, object]] = {}
    for entry in roster:
        if not isinstance(entry, dict):
            continue
        name, provider, scope = entry.get("name"), entry.get("cli"), entry.get("scope")
        if (
            not isinstance(name, str)
            or FRIEND_NAME_RE.fullmatch(name) is None
            or not isinstance(provider, str)
            or FRIEND_NAME_RE.fullmatch(provider) is None
            or scope not in {"doc", "repo"}
        ):
            continue
        rows[name] = {
            "name": name,
            "provider": provider,
            "scope": scope,
            "round": 0,
            "status": "pending",
        }
    return rows


def _metadata_status(value: object) -> str:
    """Map a diagnostic-bearing friend status to a small safe vocabulary."""
    if not isinstance(value, str):
        return "pending"
    normalized = value.lower()
    if (
        normalized == "ok"
        or normalized.startswith("ok ")
        or normalized in {"succeeded", "completed"}
    ):
        return "succeeded"
    if normalized == "failed" or normalized.startswith("failed:"):
        return "failed"
    if normalized == "skipped" or normalized.startswith("skipped:"):
        return "skipped"
    return "pending"


def _metadata_rows(meta: dict[str, Any], rows: dict[str, dict[str, object]]) -> None:
    """Overlay validated historical friend rows without exposing diagnostics."""
    saved = meta.get("friends")
    if not isinstance(saved, list):
        return
    for entry in saved:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        round_no = entry.get("round")
        if (
            not isinstance(name, str)
            or FRIEND_NAME_RE.fullmatch(name) is None
            or type(round_no) is not int
            or round_no < 1
        ):
            continue
        prior = rows.get(name)
        scope = entry.get("scope")
        if scope not in {"doc", "repo"}:
            scope = prior["scope"] if prior is not None else "unknown"
        provider = entry.get("provider", entry.get("cli"))
        if not isinstance(provider, str) or FRIEND_NAME_RE.fullmatch(provider) is None:
            provider = prior["provider"] if prior is not None else "unknown"
        status = _metadata_status(entry.get("status"))
        if prior is not None:
            prior_round = prior["round"]
            assert isinstance(prior_round, int)
            if round_no < prior_round:
                continue
        rows[name] = {
            "name": name,
            "provider": provider,
            "scope": scope,
            "round": round_no,
            "status": status,
        }


def _friends(meta: dict[str, Any], events: Iterable[EventRecord]) -> dict[str, object]:
    rows = _roster_rows(meta)
    _metadata_rows(meta, rows)
    for event in events:
        if event.type not in {"friend_finished", "friend_failed"}:
            continue
        payload = event.payload
        name = payload["friend"]
        provider = payload["provider"]
        round_no = payload["round"]
        event_status = payload["status"]
        assert isinstance(name, str)
        assert isinstance(provider, str)
        assert isinstance(round_no, int)
        assert isinstance(event_status, str)
        row = rows.setdefault(
            name,
            {
                "name": name,
                "provider": provider,
                "scope": "unknown",
                "round": 0,
                "status": "pending",
            },
        )
        prior_round = row["round"]
        assert isinstance(prior_round, int)
        row["round"] = max(prior_round, round_no)
        row["status"] = event_status
    ordered = [rows[name] for name in sorted(rows)]
    failed = sum(row["status"] == "failed" for row in ordered)
    finished = sum(row["status"] in {"succeeded", "failed"} for row in ordered)
    return {"total": len(ordered), "finished": finished, "failed": failed, "rows": ordered}


def _rounds(
    meta: dict[str, Any], events: Iterable[EventRecord], state: str
) -> dict[str, int | None]:
    saved = meta.get("rounds_run")
    saved_rounds = saved if type(saved) is int and saved >= 0 else 0
    observed: list[int] = []
    for event in events:
        if event.type not in {"friend_finished", "friend_failed", "round_finished"}:
            continue
        round_no = event.payload["round"]
        assert isinstance(round_no, int)
        observed.append(round_no)
    current = max([saved_rounds, *observed], default=0)
    return {"current": current, "final": current if state in {"terminal", "halted"} else None}


def _latest_invocation(events: list[EventRecord]) -> list[EventRecord]:
    """Discard completed earlier attempts when a halted run has resumed."""
    for index in range(len(events) - 1, -1, -1):
        if events[index].type == "run_started":
            return events[index:]
    return events


def _state(meta: dict[str, Any], events: list[EventRecord]) -> tuple[str, str | None, str | None]:
    finished = next((event for event in reversed(events) if event.type == "run_finished"), None)
    if finished is not None:
        status = finished.payload.get("status")
        action = finished.payload.get("next_action")
        return (
            "terminal",
            status if isinstance(status, str) else None,
            action if isinstance(action, str) else None,
        )
    if events:
        return "live", None, None
    lifecycle = meta.get("lifecycle_state")
    if lifecycle == "terminal":
        return "terminal", None, None
    if isinstance(lifecycle, str) and ("waiting" in lifecycle or "halt" in lifecycle):
        return "halted", None, "resume"
    if lifecycle == "running":
        return "live", None, None
    return "unknown", None, None


def _next_action(
    state: str, reported: str | None, *, mode: str | None, claims: dict[str, object]
) -> str:
    if reported is not None:
        return reported
    if state == "halted":
        return "resume"
    by_status = claims["by_status"]
    if (
        state == "terminal"
        and mode == "gate"
        and isinstance(by_status, dict)
        and by_status.get("pending")
    ):
        return "resolve"
    if state == "live":
        return "watch"
    return "inspect_report"


def summarize(run_dir: Path, *, root: Path) -> dict[str, object]:
    """Reconstruct a stable status schema entirely from existing artifacts."""
    meta, has_metadata = _read_optional_json(
        run_dir / "run.json", root=root, label="saved run metadata"
    )
    events = _latest_invocation(_read_events(run_dir / "events.jsonl", root=root))
    if not has_metadata and not events:
        raise UsageError(f"{run_dir} is not a run directory: no run.json or valid lifecycle events")
    ledger_records = _read_ledger(run_dir / "claims.jsonl", root=root)
    claims = _claim_counts(ledger_records)
    started = next((event for event in events if event.type == "run_started"), None)
    mode = meta.get("mode") if isinstance(meta.get("mode"), str) else None
    profile = meta.get("profile") if isinstance(meta.get("profile"), str) else None
    if started is not None:
        if isinstance(started.payload.get("mode"), str):
            mode = started.payload["mode"]
        if isinstance(started.payload.get("profile"), str):
            profile = started.payload["profile"]
    state, outcome, reported_action = _state(meta, events)
    downgrades = meta.get("downgrades")
    raw_qualification = meta.get("qualification")
    qualification: dict[str, object] | None = None
    if isinstance(raw_qualification, dict):
        keys = {"policy", "qualified", "qualifying_names", "provider_families", "reason"}
        if set(raw_qualification) == keys and isinstance(raw_qualification["policy"], str):
            qualification = {key: raw_qualification[key] for key in keys}
    friends = _friends(meta, events)
    saved_friends = meta.get("friends")
    review_completeness = from_friends(saved_friends if isinstance(saved_friends, list) else [])
    rows = friends["rows"]
    assert isinstance(rows, list)
    started_scope = started.payload.get("scope") if started is not None else None
    if isinstance(started_scope, str) and started_scope in {"doc", "repo"}:
        scope = started_scope
    elif rows:
        scopes = {row.get("scope") for row in rows if isinstance(row, dict)}
        scope = "repo" if "repo" in scopes else "doc" if "doc" in scopes else "unknown"
    else:
        scope = "unknown"
    return {
        "version": STATUS_SCHEMA_VERSION,
        "run_id": run_dir.name,
        "path": str(run_dir),
        "state": state,
        "outcome": outcome,
        "mode": mode,
        "profile": profile,
        "claims": claims,
        "triage": _triage(ledger_records, meta, run_dir=run_dir, root=root),
        "scope": scope,
        "rounds": _rounds(meta, events, state),
        "friends": friends,
        "review_completeness": review_completeness,
        "qualification": qualification,
        "downgrades": list(downgrades)
        if isinstance(downgrades, list) and all(isinstance(item, str) for item in downgrades)
        else [],
        "next_action": _next_action(state, reported_action, mode=mode, claims=claims),
    }


def watch_events(
    path: Path,
    *,
    root: Path,
    poll_s: float = _POLL_S,
    snapshots: Iterable[str] | None = None,
    start_at_end: bool = False,
) -> Iterator[EventRecord]:
    """Yield each complete event once and stop at ``run_finished``.

    The optional snapshots seam is solely for deterministic tests of a writer
    completing a torn tail. Production always rereads the bounded event log.
    """
    if poll_s < 0:
        raise ValueError("poll_s must be non-negative")
    emitted = 0
    initial = True
    source = iter(snapshots) if snapshots is not None else None
    while True:
        if source is None:
            events = _read_events(path, root=root)
        else:
            try:
                snapshot = next(source)
            except StopIteration:
                return
            temporary = path.with_name(f".{path.name}.status-snapshot")
            # Parse the supplied snapshot through the exact event validator
            # without writing the run: a tiny local decoder mirrors
            # read_events' only permitted recovery (an incomplete final line).
            lines = snapshot.splitlines(keepends=True)
            if lines and not lines[-1].endswith("\n"):
                lines.pop()
            events = []
            for line_no, line in enumerate(lines, start=1):
                try:
                    events.append(EventRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, UsageError, TypeError, ValueError) as exc:
                    raise UsageError(f"{temporary.name} line {line_no}: {exc}") from exc
        if initial and start_at_end:
            if any(event.type == "run_finished" for event in _latest_invocation(events)):
                return
            emitted = len(events)
        initial = False
        for event in events[emitted:]:
            yield event
            if event.type == "run_finished":
                return
        emitted = max(emitted, len(events))
        time.sleep(poll_s)


def _render(summary: dict[str, object]) -> str:
    outcome = f" ({summary['outcome']})" if summary["outcome"] else ""
    claims = summary["claims"]
    assert isinstance(claims, dict)
    by_status = claims["by_status"]
    assert isinstance(by_status, dict)
    claim_text = ", ".join(f"{name}={count}" for name, count in by_status.items()) or "none"
    lines = [
        f"{summary['run_id']}: {summary['state']}{outcome}",
        f"mode: {summary['mode'] or 'unknown'}  profile: {summary['profile'] or 'none'}  scope: {summary['scope']}",
        f"claims: {claims['total']} ({claim_text})",
    ]
    triage = summary.get("triage")
    if isinstance(triage, dict):
        findings = triage.get("final_findings")
        unresolved = triage.get("unresolved_count")
        if isinstance(findings, list) and isinstance(unresolved, int):
            rendered_findings: list[str] = []
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                claim_id = finding.get("id")
                severity = finding.get("severity")
                finding_status = finding.get("status")
                if all(isinstance(value, str) for value in (claim_id, severity, finding_status)):
                    rendered_findings.append(f"{claim_id} [{severity}, {finding_status}]")
            detail = "; ".join(rendered_findings) if rendered_findings else "none"
            lines.append(f"final findings: {detail}  unresolved={unresolved}")
    lines.append(f"next: {summary['next_action']}")
    rounds = summary["rounds"]
    if isinstance(rounds, dict):
        lines.append(f"rounds: current={rounds['current']} final={rounds['final']}")
    qualification = summary.get("qualification")
    if isinstance(qualification, dict):
        lines.append(
            f"qualification: {qualification['policy']} qualified={qualification['qualified']}"
        )
    friends = summary["friends"]
    if isinstance(friends, dict) and isinstance(friends.get("rows"), list):
        # Every row, whatever its status. Rendering only succeeded/failed made
        # a skipped friend vanish: a two-friend run with one skip printed
        # byte-identically to a one-friend run that passed, and
        # review_completeness stays None unless NO friend answered, so the
        # partial-skip case had no signal anywhere in the human output.
        for row in friends["rows"]:
            if isinstance(row, dict) and isinstance(row.get("status"), str):
                lines.append(
                    f"friend: {row['name']} {row['status']} "
                    f"scope={row['scope']} round={row['round']}"
                )
        total = friends.get("total")
        finished = friends.get("finished")
        if isinstance(total, int) and isinstance(finished, int) and finished != total:
            lines.append(f"friends: {finished} of {total} finished")
    review_completeness = summary["review_completeness"]
    if isinstance(review_completeness, dict):
        message = review_completeness.get("message")
        if isinstance(message, str):
            lines.append(f"review completeness: {message}")
    downgrades = summary["downgrades"]
    if isinstance(downgrades, list) and downgrades:
        lines.append("downgrades:")
        lines.extend(f"  - {item}" for item in downgrades)
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    run_dir, root = find_run(args.run_id, getattr(args, "out", None))
    summary = summarize(run_dir, root=root)
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(_render(summary))
    events_path = run_dir / "events.jsonl"
    if getattr(args, "watch", False) and not secure_regular_exists(events_path, root=root):
        print("afriend: live events unavailable; status cannot watch this run.", file=sys.stderr)
    elif getattr(args, "watch", False) and summary["state"] == "live":
        for event in watch_events(events_path, root=root, start_at_end=True):
            print(f"afriend: {event.type} {dict(event.payload)}", file=sys.stderr)
    return 0
