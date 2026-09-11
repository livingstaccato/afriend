"""`afriend resolve`: attest that a gate-blocking claim has been dealt with.

Spec §7.5. Appends one Resolution to a finished run's ledger and re-reports
the gate, so the workflow is a loop the shell can drive:

    afriend run spec.md --mode gate            # exit 1, names what blocks
    afriend resolve <run-id> --claim c-0001@1 \\
        --disposition fixed --evidence src/auth.py:38
                                               # exit 1, one fewer blocking
    ...                                        # exit 0 once nothing blocks

**It never edits an artifact**, and it does not pretend to verify that a
defect is gone. What it verifies is narrower and honest: whether the location
the author named actually changed since the run started (§6.4). See
resolutions.py for why a whole-artifact hash would be worthless here, and
why unverifiable evidence can record risk or rejection but cannot support
`fixed`.
"""

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

from ..errors import UsageError
from ..ids import parse_claim_id
from ..jsonio import load_json_object
from ..ledger import (
    MAX_LEDGER_BYTES,
    Claim,
    Ledger,
    Record,
    Resolution,
    _bounded_lines,
    record_from_dict,
)
from ..outcomes import json_node_count
from ..report import _sanitize_display
from ..resolutions import (
    UNVERIFIABLE,
    parse_location,
    rejection_reason,
    resolve_form_error,
    verify_location,
)
from ..reviewcompleteness import from_friends
from ..reviewstate import ReviewState
from ..runstore import default_root
from ..secureio import secure_open_read

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_EVIDENCE_REQUIREMENT = "--disposition fixed|rejected|accepted-risk --evidence PATH[:LINE]"


def _find_run(run_id: str, out: str | None) -> Path:
    """Accept either a run id or a path to a run directory.

    A path is what `afriend run` actually prints, so pasting its output
    straight back in has to work; the bare id is what §7.5's usage line
    shows.
    """
    candidate = Path(run_id)
    if candidate.is_dir():
        return candidate
    root = Path(out) if out else default_root()
    resolved = root / run_id
    if not resolved.is_dir():
        raise UsageError(
            f"no such run: {run_id!r} (looked in {root}). Pass the run "
            "directory path that `afriend run` printed, or --out if the run "
            "was written somewhere else."
        )
    return resolved


def _load_meta(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    if not path.is_file():
        raise UsageError(f"{run_dir} is not a run directory: no run.json")
    return load_json_object(path, label="saved run metadata")


def _claim_states(meta: dict[str, Any]) -> dict[str, str]:
    """Read persisted claim states, of which a run may honestly have none.

    Only a run that adjudicated claims records states, so a report-mode run
    has no map and every unresolved non-advisory claim is treated
    conservatively. A map that is present but malformed is a different
    thing, and must not be guessed at.
    """
    raw = meta.get("claim_states")
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(
        isinstance(claim_id, str) and isinstance(state, str) for claim_id, state in raw.items()
    ):
        raise UsageError(
            "saved run metadata has malformed claim_states; expected string keys and values"
        )
    return raw


def _unresolved_claims(review: ReviewState, meta: dict[str, Any]) -> list[Claim]:
    for claim in review.claims:
        parse_claim_id(claim.id)
        if claim.severity not in _SEVERITY_ORDER:
            raise UsageError(
                f"malformed claim severity: {claim.severity!r} "
                f"(expected one of {', '.join(_SEVERITY_ORDER)})"
            )
    states = _claim_states(meta)
    return sorted(
        review.blocking(states),
        key=lambda claim: (_SEVERITY_ORDER.get(claim.severity, len(_SEVERITY_ORDER)), claim.id),
    )


def _read_discovery_records(path: Path, *, run_dir: Path) -> list[Record]:
    """Read the ledger with Ledger's bounds but without writer initialization."""
    try:
        descriptor = secure_open_read(path, root=run_dir)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise UsageError(f"cannot read ledger {path}: {exc}") from exc
    try:
        if os.fstat(descriptor).st_size > MAX_LEDGER_BYTES:
            raise UsageError(f"ledger {path} file exceeds the {MAX_LEDGER_BYTES}-byte limit")
        records: list[Record] = []
        for line_no, raw in enumerate(_bounded_lines(descriptor, path), start=1):
            if not raw.strip():
                continue
            try:
                decoded = raw.decode("utf-8")
                parsed = json.loads(decoded)
                json_node_count(parsed, f"ledger record {line_no}")
                records.append(record_from_dict(parsed))
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                RecursionError,
                TypeError,
                ValueError,
            ) as exc:
                raise UsageError(f"{path}:{line_no}: invalid ledger record: {exc}") from exc
            except UsageError as exc:
                raise UsageError(f"{path}:{line_no}: {exc}") from exc
        return records
    except OSError as exc:
        raise UsageError(f"cannot read ledger {path}: {exc}") from exc
    finally:
        os.close(descriptor)


def _location(claim: Claim) -> str:
    """Render the durable finding location, without inferring a new one."""
    return claim.location or "not recorded"


def _display(value: object) -> str:
    """Keep adversarial ledger prose to one safe terminal line."""
    return _sanitize_display(value, single_line=True)


def _render_claim(claim: Claim) -> list[str]:
    return [
        f"{claim.id} [{claim.severity}] {_display(claim.claim)}",
        f"  location: {_display(_location(claim))}",
        f"  evidence: {_display(claim.evidence)}",
        f"  resolution requires: {_EVIDENCE_REQUIREMENT}",
    ]


def _write_command(run_dir: Path, claim: Claim) -> str:
    run_arg = shlex.quote(_display(str(run_dir)))
    claim_arg = shlex.quote(claim.id)
    return (
        f"afriend resolve {run_arg} --claim {claim_arg} "
        f"--disposition <fixed|rejected|accepted-risk> --evidence PATH[:LINE]"
    )


def _saved_path(source: dict[str, Any], field: str) -> Path | None:
    """A path field from saved metadata, or None when absent."""
    value = source.get(field.rsplit(".", 1)[-1])
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise UsageError(f"saved run metadata {field} must be a string, got {type(value).__name__}")
    return Path(value)


def _saved_round(meta: dict[str, Any]) -> int:
    """The round a resolution is recorded against."""
    value = meta.get("rounds_run", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise UsageError(f"saved run metadata rounds_run must be a positive integer, got {value!r}")
    return value


def _cmd_discovery(args: argparse.Namespace, run_dir: Path, meta: dict[str, Any]) -> int:
    """Render read-only unresolved-claim discovery from the durable ledger."""
    review = ReviewState.replay(_read_discovery_records(run_dir / "claims.jsonl", run_dir=run_dir))
    claims = _unresolved_claims(review, meta)
    if not claims:
        # An empty ledger is not the same as a clean review. With every friend
        # failed there are no claims at all, and reporting "no action needed"
        # for that is the repo's own "a skip looks exactly like a pass" in the
        # command whose job is to say what still blocks the gate. The friend
        # rows that prove it are already in the meta loaded above, and this is
        # the helper `afriend status` uses for the same decision.
        completeness = from_friends(
            meta["friends"] if isinstance(meta.get("friends"), list) else []
        )
        if completeness is not None:
            message = completeness.get("message")
            print(
                "No unresolved claims, but this run did not complete a review: "
                f"{message if isinstance(message, str) else 'no friend answered'}"
            )
            print("Resolution cannot clear a gate that never gathered evidence.")
            return 1
        print("No unresolved claims. No resolution action is needed.")
        return 0

    if getattr(args, "list", False):
        for index, claim in enumerate(claims):
            if index:
                print()
            print("\n".join(_render_claim(claim)))
        print()
        run_arg = shlex.quote(_display(str(run_dir)))
        print(f"next: afriend resolve {run_arg} --next")
        return 0

    highest_priority = claims[0].severity
    candidates = [claim for claim in claims if claim.severity == highest_priority]
    if len(candidates) != 1:
        choices = ", ".join(claim.id for claim in candidates)
        raise UsageError(
            f"multiple {highest_priority} unresolved claims are equally highest priority; "
            f"choose --claim explicitly: {choices}"
        )
    claim = candidates[0]
    print("\n".join(_render_claim(claim)))
    print(f"next: {_write_command(run_dir, claim)}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    run_dir = _find_run(args.run_id, args.out)
    meta = _load_meta(run_dir)
    form_error = resolve_form_error(
        discovery=bool(getattr(args, "list", False) or getattr(args, "next", False)),
        claim=getattr(args, "claim", None),
        disposition=getattr(args, "disposition", None),
        evidence=getattr(args, "evidence", None),
        author=getattr(args, "author", None),
    )
    if form_error is not None:
        raise UsageError(form_error)
    if getattr(args, "list", False) or getattr(args, "next", False):
        return _cmd_discovery(args, run_dir, meta)

    ledger = Ledger(run_dir / "claims.jsonl")
    review = ReviewState.replay(ledger.records())

    parse_claim_id(args.claim)  # rejects a malformed id with a usage error
    claims = review.claims
    by_id = {c.id: c for c in claims}
    if args.claim not in by_id:
        raise UsageError(
            f"run {run_dir.name} has no claim {args.claim!r}. "
            f"Known: {', '.join(sorted(by_id)) or 'none'}"
        )

    location = parse_location(args.evidence)
    if location is None:
        # §6.4: evidence must name a location. Prose alone leaves nothing to
        # verify, and recording it would make every resolution look equally
        # well-supported.
        raise UsageError(
            f"--evidence must name a location (e.g. src/auth.py:38), got "
            f"{args.evidence!r}. §6.4 requires one: a resolution with no "
            "location is an assertion nothing can check."
        )

    # The nested snapshot is the repository identity. run.json used to mirror
    # repo_root and the commit at the top level for v0.2 readers; it no longer
    # does, and reading the mirror would read a field nothing writes.
    snapshot = meta.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    # Typed before use. This module already treats run.json as untrusted
    # (_claim_states raises UsageError for a malformed claim_states, and
    # status._rounds type-checks rounds_run with `type(saved) is int`), but
    # these three reads coerced whatever was there -- so a truncated,
    # hand-edited or foreign-version run.json escaped as a bare TypeError
    # traceback, since cli.main catches only AfError.
    repo_root = _saved_path(snapshot, "snapshot.repo_root")
    frozen_dir = run_dir / "artifact"
    frozen = next(iter(frozen_dir.iterdir()), None) if frozen_dir.is_dir() else None
    artifact_path = _saved_path(meta, "artifact_path")
    verified = verify_location(
        location,
        repo_root,
        snapshot.get("commit"),
        frozen_artifact=frozen,
        artifact_path=artifact_path,
    )

    refusal = rejection_reason(args.disposition, verified)
    if refusal:
        raise UsageError(refusal)

    resolution = Resolution(
        claim_id=args.claim,
        disposition=args.disposition,
        author=args.author or os.environ.get("USER") or "unknown",
        evidence=args.evidence,
        round=_saved_round(meta),
        verified=verified,
    )
    ledger.append(resolution)
    review.apply(resolution)

    if verified == UNVERIFIABLE:
        # A fixed disposition was refused above. For accepted risk or a
        # rejected claim, record the attestation but say that nothing was
        # independently checked.
        print(
            f"afriend: recorded, but {location.path} could not be reconstructed "
            "from this run; the resolution is an attestation only.",
            file=sys.stderr,
        )

    states = _claim_states(meta)
    blocking = review.blocking(states)

    print(f"{resolution.claim_id} {args.disposition} ({verified})")
    if blocking:
        print(
            f"afriend: gate blocked -- {len(blocking)} claim(s) still need a "
            "resolution: " + ", ".join(c.id for c in blocking),
            file=sys.stderr,
        )
        return 1
    print("gate clear")
    return 0
