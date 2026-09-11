"""Verifying a resolution, and deciding whether a gate is clear -- §6.4, §7.5.

**A resolution is an attestation, and this module says so rather than
implying more.** The runner cannot know that a defect was fixed; it can only
check whether the location the author named actually changed. §6.4 is built
around that limit:

* Comparing a whole-artifact hash is not validation. It has the same value
  for every claim in a run, so one trailing newline would satisfy it twelve
  times over.
* A resolution is never rejected merely because the reviewed artifact is
  unchanged. A valid fix for a claim about `docs/design.md` frequently lands
  in `src/auth.py`, and requiring the artifact to change would force dummy
  edits to clear a gate. So what gets verified is the location the evidence
  names, wherever that is.
* A location the runner cannot reconstruct is `unverifiable`. That is valid
  for `rejected` and `accepted-risk`, but cannot support a claim that the
  defect was `fixed`.

A `fixed` disposition therefore requires `location-changed`: unchanged
evidence contradicts the attestation, while unverifiable evidence proves
nothing. Use `accepted-risk` when verification is intentionally unavailable.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from .ledger import Claim, Resolution
from .verdicts import GATE_CLEARING_STATES, GATE_EXEMPT_STATES

DISPOSITIONS = ("fixed", "rejected", "accepted-risk")

LOCATION_CHANGED = "location-changed"
LOCATION_UNCHANGED = "location-unchanged"
UNVERIFIABLE = "unverifiable"

# `path`, `path:12`, or `path:12-40`. The line part is optional and, when
# present, narrows the comparison to those lines -- a fix to line 38 of a
# 900-line file should not be judged by whether anything else in the file
# moved.
_LOCATION_RE = re.compile(r"^(?P<path>[^\s:]+)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?")


def resolve_form_error(
    *,
    discovery: bool,
    claim: str | None,
    disposition: str | None,
    evidence: str | None,
    author: str | None,
) -> str | None:
    """Return the missing-or-conflicting contract error for ``resolve``.

    Discovery deliberately has no mutation fields.  The established write
    form remains all-or-nothing: accepting a partial form would invite a
    caller to mistake inspection for a recorded attestation.
    """
    write_fields = {
        "claim": claim,
        "disposition": disposition,
        "evidence": evidence,
    }
    if discovery:
        if any(value is not None for value in write_fields.values()) or author is not None:
            return "--list/--next cannot be combined with resolution write fields"
        return None
    missing = [field for field, value in write_fields.items() if value is None]
    if missing:
        return "the following arguments are required for a resolution: " + ", ".join(
            f"--{field}" for field in missing
        )
    return None


@dataclass(frozen=True)
class Location:
    path: str
    start: int | None = None
    end: int | None = None


def parse_location(evidence: str) -> Location | None:
    """Pull a file location out of an evidence string, or None.

    §6.4 requires that `evidence` name a location; prose alone leaves nothing
    to verify. The first whitespace-delimited token is tried, so
    "src/auth.py:38 now checks exp" works as well as a bare path.
    """
    token = evidence.strip().split()[0] if evidence.strip() else ""
    match = _LOCATION_RE.match(token)
    if not match or ("/" not in token and "." not in token):
        # Require something that at least looks like a path. A bare word is
        # prose, and treating it as a filename produces a confusing
        # "unverifiable" instead of an honest "you named no location".
        return None
    start = match.group("start")
    end = match.group("end")
    return Location(
        path=match.group("path"),
        start=int(start) if start else None,
        end=int(end) if end else None,
    )


def _slice_lines(text: str, location: Location) -> str:
    if location.start is None:
        return text
    lines = text.splitlines()
    start = max(location.start - 1, 0)
    end = location.end if location.end is not None else location.start
    return "\n".join(lines[start:end])


class _GitUnavailable(Exception):
    """git could not be run at all -- absent, not executable, or refused by
    the OS. Distinct from git running and answering "no": an answer we can
    reason about, versus no answer at all."""


def _git_ignores(repo: Path, relpath: str) -> bool:
    """Whether git would have EXCLUDED `relpath` from the snapshot commit.

    Named for what it returns. The predecessor was called `_git_tracks` and
    returned `check-ignore`'s "is ignored" answer unchanged, so its name and
    docstring asserted the inverse of its result. The single call site read
    it correctly as "git never tracks it", which left the behaviour right and
    the contract backwards -- a second caller written from the name would
    have inverted the one check that makes a `fixed` disposition mean
    anything.

    `isolation.snapshot_commit` builds the snapshot with `git add -A`, which
    honours .gitignore -- so an ignored path is absent from the snapshot tree
    whether or not it existed at the time. Without this distinction,
    "not in the snapshot" was read as "created since the snapshot", and every
    generated, vendored or ignored path passed that check.

    Anything other than a clean "not ignored" answer counts as ignored, i.e.
    as unverifiable: for a disposition that asserts a fix landed, the
    conservative direction is to refuse. The old `except OSError: return
    False` did the opposite -- it reported "not ignored", which falls through
    to LOCATION_CHANGED and rubber-stamps `fixed`, the exact outcome this
    docstring says to avoid.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", relpath],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise _GitUnavailable(str(exc)) from exc
    # 1 is git's "not ignored"; 0 is "ignored"; anything else is an error,
    # and an error is not a clean "not ignored".
    return result.returncode != 1


def _git_has_commit(repo: Path, sha: str) -> bool:
    """Whether the snapshot commit itself is present in this repository.

    `_git_show` returns None for every nonzero git exit, which collapses two
    different facts into one: "that path is not in that tree" and "that tree
    is not here". Only the first supports reading absence as "created since
    the snapshot". Without this check, a snapshot object that had been
    garbage-collected, or a run directory carried to a different clone, made
    every existing tracked file report LOCATION_CHANGED -- which
    `rejection_reason` accepts as support for `fixed`, approving a fix
    against no baseline whatsoever.
    """
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise _GitUnavailable(str(exc)) from exc
    return result.returncode == 0


def _git_show(repo: Path, sha: str, relpath: str) -> str | None:
    """The file's content at the snapshot commit, or None if it was not
    tracked there (a newly created file, or a path outside the repo).

    A nonzero exit means git answered "not in that tree". Git failing to run
    at all is not that answer, and must not be flattened into it: this call
    was the one `subprocess.run` on this path with no OSError guard, while
    the identical call in `commands/environment.py` has one, so a host
    without git got a bare traceback out of `cli.main` instead of a refusal.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{sha}:{relpath}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise _GitUnavailable(str(exc)) from exc
    if result.returncode != 0:
        return None
    return result.stdout


def verify_location(
    location: Location,
    repo_root: Path | None,
    snapshot_sha: str | None,
    frozen_artifact: Path | None = None,
    artifact_path: Path | None = None,
) -> str:
    """Compare the named location now against how the run first saw it.

    Two reconstruction sources, in order: the frozen artifact copy when the
    location IS the reviewed artifact, and the repository snapshot for
    anything else inside the repo. Neither available means `unverifiable` --
    which is a real answer, not a failure.
    """
    named = Path(location.path)
    artifact = artifact_path.absolute() if artifact_path is not None else None

    if named.is_absolute() and artifact is not None and named.absolute() == artifact:
        current_path = named
    elif artifact is not None and named == Path(artifact.name):
        current_path = artifact
    elif repo_root is not None:
        resolved_root = repo_root.resolve()
        candidate = named if named.is_absolute() else resolved_root / named
        current_path = candidate.resolve(strict=False)
        try:
            current_path.relative_to(resolved_root)
        except ValueError:
            return UNVERIFIABLE
    else:
        return UNVERIFIABLE

    is_artifact = artifact is not None and current_path.absolute() == artifact
    if is_artifact and frozen_artifact is not None:
        if not frozen_artifact.is_file() or not current_path.is_file():
            return UNVERIFIABLE
        before = _slice_lines(
            frozen_artifact.read_text(encoding="utf-8", errors="replace"), location
        )
        after = _slice_lines(current_path.read_text(encoding="utf-8", errors="replace"), location)
        return LOCATION_CHANGED if before != after else LOCATION_UNCHANGED

    if repo_root is None or snapshot_sha is None:
        return UNVERIFIABLE

    try:
        resolved_root = repo_root.resolve()
        relpath = str(current_path.resolve(strict=False).relative_to(resolved_root))
    except ValueError:
        # Outside the repository: nothing to reconstruct it from.
        return UNVERIFIABLE

    try:
        before_text = _git_show(resolved_root, snapshot_sha, relpath)
        exists_now = current_path.is_file()
        if before_text is None and not _git_has_commit(resolved_root, snapshot_sha):
            # The snapshot is gone, so "absent from it" carries no
            # information about whether anything moved.
            return UNVERIFIABLE
        if before_text is None and not exists_now:
            return UNVERIFIABLE
        if before_text is None and _git_ignores(resolved_root, relpath):
            # Absent from the snapshot because git would never have captured
            # it, not because it appeared since. Nothing can be reconstructed
            # to compare against, so this is unverifiable -- which refuses
            # `fixed` instead of rubber-stamping it.
            return UNVERIFIABLE
    except _GitUnavailable:
        # No baseline can be reconstructed without git, and a verifier that
        # cannot check must refuse rather than report a change it did not
        # observe.
        return UNVERIFIABLE
    if before_text is None or not exists_now:
        # Created since the snapshot, or deleted since it. Either way the
        # location is not what it was.
        return LOCATION_CHANGED

    before = _slice_lines(before_text, location)
    after = _slice_lines(current_path.read_text(encoding="utf-8", errors="replace"), location)
    return LOCATION_CHANGED if before != after else LOCATION_UNCHANGED


def rejection_reason(disposition: str, verified: str) -> str | None:
    """Whether the verification result can support this disposition.

    A `fixed` disposition must name a verifiably changed location. `rejected`
    and `accepted-risk` make no claim about a change, so unchanged or
    unverifiable evidence is consistent with both.
    """
    if disposition == "fixed" and verified == UNVERIFIABLE:
        return (
            "a fixed resolution must name evidence this run can verify; "
            "use accepted-risk when verification is intentionally unavailable"
        )
    if disposition == "fixed" and verified == LOCATION_UNCHANGED:
        return (
            "disposition 'fixed' names a location that has not changed since "
            "the run started. A fix that landed elsewhere should name that "
            "location instead; if nothing changed, the disposition is "
            "'rejected' or 'accepted-risk'."
        )
    return None


def blocking_claims(
    claims: list[Claim],
    states: dict[str, str],
    resolutions: list[Resolution],
) -> list[Claim]:
    """The claims standing between this run and a clear gate -- §7.5.

    Three things take a claim off the gate: `settled-refuted` (the judges
    agreed it was wrong), `superseded` (its successor carries the question),
    or an explicit Resolution. `discarded` blocks -- nobody could check it.
    Advisory claims never block either, because their lens
    deliberately does not demand a failure scenario -- "this is more than you
    need" is judgment, and gating on it would silence the lens entirely.

    A claim in a NON-terminal state blocks too. `contested` is not a pass;
    the run simply had not finished deciding it.
    """
    resolved = {r.claim_id for r in resolutions}
    blocking = []
    for claim in claims:
        if claim.advisory or claim.id in resolved:
            continue
        if states.get(claim.id) in GATE_CLEARING_STATES | GATE_EXEMPT_STATES:
            continue
        blocking.append(claim)
    return blocking
