"""Deterministically compose explicit review evidence into one Markdown artifact.

This module deliberately receives paths and Git range arguments directly.  It
does not discover chat context, infer an artifact, or attach arbitrary host
metadata to the review evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import subprocess
import tempfile
from typing import cast

from .errors import UsageError
from .jsonio import read_bounded_bytes

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_INPUT_ROLES = frozenset({"plan", "review"})
_CHANGE_KINDS = frozenset({"worktree", "range"})
_MANIFEST_VERSION = 1
MAX_CONTEXT_SOURCE_BYTES = 4 * 1024 * 1024
MAX_CHANGE_BYTES = 4 * 1024 * 1024
MAX_CHANGE_MEMBERS = 64
MAX_CHANGESET_BYTES = 8 * 1024 * 1024
_MAX_GIT_ERROR_BYTES = 64 * 1024


class ContextIntent(StrEnum):
    ARTIFACT = "artifact"
    VALIDATE_PLAN = "validate-plan"
    VALIDATE_REVIEW = "validate-review"
    VALIDATE_CHAIN = "validate-chain"


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_digest(value: object, field: str = "digest") -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise UsageError(f"review context {field} must be sha256:<64 lowercase hex digits>")
    return value


def _canonical_path(value: object, field: str) -> Path:
    if not isinstance(value, Path):
        raise UsageError(f"review context {field} must be a Path")
    if not value.is_absolute() or value != value.resolve():
        raise UsageError(f"review context {field} must be a canonical absolute path")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise UsageError(f"review context {field} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ContextInput:
    role: str
    label: str
    source_path: Path
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in _INPUT_ROLES:
            raise UsageError("review context input role must be plan or review")
        _nonempty_string(self.label, "input label")
        _canonical_path(self.source_path, "input source_path")
        _validate_digest(self.digest, "input digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "label": self.label,
            "path": str(self.source_path),
            "digest": self.digest,
        }


@dataclass(frozen=True)
class ChangeMember:
    kind: str
    label: str
    digest: str
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _CHANGE_KINDS:
            raise UsageError("review context change kind must be worktree or range")
        _nonempty_string(self.label, "change label")
        _validate_digest(self.digest, "change digest")
        if self.kind == "worktree":
            if self.start is not None or self.end is not None:
                raise UsageError("review context worktree change must not have range endpoints")
            return
        if (
            not isinstance(self.start, str)
            or _COMMIT_RE.fullmatch(self.start) is None
            or not isinstance(self.end, str)
            or _COMMIT_RE.fullmatch(self.end) is None
        ):
            raise UsageError("review context range change endpoints must be immutable commits")

    def to_dict(self) -> dict[str, str]:
        data = {"kind": self.kind, "label": self.label, "digest": self.digest}
        if self.kind == "range":
            assert self.start is not None and self.end is not None
            data["start"] = self.start
            data["end"] = self.end
        return data


@dataclass(frozen=True)
class ContextManifest:
    intent: ContextIntent
    repository_root: Path
    inputs: tuple[ContextInput, ...]
    changes: tuple[ChangeMember, ...]
    output_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ContextIntent):
            raise UsageError("review context intent must be a ContextIntent")
        _canonical_path(self.repository_root, "repository_root")
        if not isinstance(self.inputs, tuple):
            raise UsageError("review context manifest inputs must be a tuple")
        if not isinstance(self.changes, tuple):
            raise UsageError("review context manifest changes must be a tuple")
        if not self.inputs:
            raise UsageError("review context manifest requires at least one plan or review input")
        if not all(isinstance(item, ContextInput) for item in self.inputs):
            raise UsageError("review context manifest inputs must be ContextInput values")
        if len({item.role for item in self.inputs}) != len(self.inputs):
            raise UsageError("review context manifest has duplicate input roles")
        if not self.changes:
            raise UsageError("review context manifest requires at least one change member")
        if not all(isinstance(item, ChangeMember) for item in self.changes):
            raise UsageError("review context manifest changes must be ChangeMember values")
        if self.output_sha256 is not None:
            _validate_digest(self.output_sha256, "output_sha256")

    def to_dict(self) -> dict[str, object]:
        if self.output_sha256 is None:
            raise UsageError("review context manifest output_sha256 is required for serialization")
        return {
            "version": _MANIFEST_VERSION,
            "intent": self.intent.value,
            "repository": {"root": str(self.repository_root)},
            "inputs": [item.to_dict() for item in self.inputs],
            "changes": [item.to_dict() for item in self.changes],
            "output_sha256": self.output_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> ContextManifest:
        if type(value) is not dict:
            raise UsageError("review context manifest must be a JSON object")
        data = cast(dict[str, object], value)
        expected = {"version", "intent", "repository", "inputs", "changes", "output_sha256"}
        if set(data) != expected:
            raise UsageError("review context manifest has unexpected fields")
        if type(data["version"]) is not int or data["version"] != _MANIFEST_VERSION:
            raise UsageError("review context manifest version is unsupported")
        raw_intent = data["intent"]
        if not isinstance(raw_intent, str):
            raise UsageError("review context manifest intent is invalid")
        try:
            intent = ContextIntent(raw_intent)
        except ValueError as exc:
            raise UsageError("review context manifest intent is invalid") from exc
        repository = data["repository"]
        if type(repository) is not dict or set(repository) != {"root"}:
            raise UsageError("review context manifest repository must contain only root")
        root = repository["root"]
        if not isinstance(root, str):
            raise UsageError("review context manifest repository root must be a string")
        raw_inputs = data["inputs"]
        raw_changes = data["changes"]
        if not isinstance(raw_inputs, list) or not isinstance(raw_changes, list):
            raise UsageError("review context manifest inputs and changes must be arrays")
        inputs: list[ContextInput] = []
        for item in raw_inputs:
            if type(item) is not dict or set(item) != {"role", "label", "path", "digest"}:
                raise UsageError("review context manifest input has unexpected fields")
            if not all(
                isinstance(item[field], str) for field in ("role", "label", "path", "digest")
            ):
                raise UsageError(
                    "review context manifest input path and identity fields must be strings"
                )
            inputs.append(
                ContextInput(item["role"], item["label"], Path(item["path"]), item["digest"])
            )
        changes: list[ChangeMember] = []
        for item in raw_changes:
            if type(item) is not dict or not isinstance(item.get("kind"), str):
                raise UsageError("review context manifest change must be an object")
            expected_change = (
                {"kind", "label", "digest"}
                if item["kind"] == "worktree"
                else {"kind", "label", "digest", "start", "end"}
            )
            if set(item) != expected_change:
                raise UsageError("review context manifest change has unexpected fields")
            changes.append(
                ChangeMember(
                    cast(str, item["kind"]),
                    cast(str, item["label"]),
                    cast(str, item["digest"]),
                    cast(str | None, item.get("start")),
                    cast(str | None, item.get("end")),
                )
            )
        return cls(
            intent,
            Path(root),
            tuple(inputs),
            tuple(changes),
            _validate_digest(data["output_sha256"], "output_sha256"),
        )


def load_manifest(path: Path) -> ContextManifest:
    """Load one strict composer sidecar without admitting arbitrary metadata."""
    from .jsonio import decode_json_object

    target = Path(path).absolute()
    payload = read_bounded_bytes(target, label="review context manifest")
    return ContextManifest.from_dict(
        decode_json_object(payload, path=target, label="review context manifest")
    )


def select_intent(*, plan: bool, review: bool, has_changes: bool) -> ContextIntent:
    """Choose the sole review question permitted by the supplied roles."""
    if type(plan) is not bool or type(review) is not bool or type(has_changes) is not bool:
        raise UsageError("review context role selection values must be booleans")
    if not has_changes:
        return ContextIntent.ARTIFACT
    if plan and review:
        return ContextIntent.VALIDATE_CHAIN
    if plan:
        return ContextIntent.VALIDATE_PLAN
    if review:
        return ContextIntent.VALIDATE_REVIEW
    raise UsageError("review context changes require a plan or review input")


def _git_error(args: tuple[str, ...], stderr: bytes) -> UsageError:
    detail = stderr.decode("utf-8", errors="replace").strip() or "git command failed"
    return UsageError(f"cannot compose review context: git {' '.join(args)} failed: {detail}")


def _git_bytes(
    repo: Path,
    *args: str,
    limit: int = MAX_CHANGE_BYTES,
    allowed_returncodes: frozenset[int] = frozenset({0}),
) -> bytes:
    """Run a fixed Git argv vector while retaining at most ``limit`` output bytes."""
    try:
        process = subprocess.Popen(
            ["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise UsageError(f"cannot compose review context: cannot run git: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None
    output = bytearray()
    errors = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    exceeded = False
    while selector.get_map():
        for key, _event in selector.select():
            chunk = os.read(key.fd, 64 * 1024)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            if key.data == "stdout":
                if len(output) + len(chunk) > limit:
                    exceeded = True
                    process.kill()
                else:
                    output.extend(chunk)
            elif len(errors) < _MAX_GIT_ERROR_BYTES:
                errors.extend(chunk[: _MAX_GIT_ERROR_BYTES - len(errors)])
    returncode = process.wait()
    if exceeded:
        raise UsageError(
            f"cannot compose review context: git output exceeds the {limit}-byte limit"
        )
    if returncode not in allowed_returncodes:
        raise _git_error(args, bytes(errors))
    return bytes(output)


def _git_text(repo: Path, *args: str) -> str:
    payload = _git_bytes(repo, *args, limit=_MAX_GIT_ERROR_BYTES)
    try:
        return payload.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise UsageError("cannot compose review context: git returned invalid UTF-8") from exc


def _repository_root(repo: Path) -> Path:
    try:
        candidate = Path(repo).resolve(strict=True)
    except OSError as exc:
        raise UsageError(
            f"cannot compose review context: repository is unavailable: {repo}: {exc}"
        ) from exc
    if not candidate.is_dir():
        raise UsageError(
            f"cannot compose review context: repository is not a directory: {candidate}"
        )
    root = Path(_git_text(candidate, "rev-parse", "--show-toplevel")).resolve()
    if root != candidate:
        raise UsageError(
            "cannot compose review context: repository must be the exact Git worktree root "
            f"(got {candidate}, root is {root})"
        )
    return root


def _resolve_commit(repo: Path, token: object) -> str:
    if not isinstance(token, str) or not token or "\0" in token or token.startswith("-"):
        raise UsageError("review context range endpoint is invalid")
    raw = _git_text(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", token)
    if _COMMIT_RE.fullmatch(raw) is None:
        raise UsageError("review context range endpoint did not resolve to one commit identity")
    object_type = _git_text(repo, "cat-file", "-t", raw)
    if object_type != "commit":
        raise UsageError("review context range endpoint must resolve to a commit")
    return raw


def _resolve_range(repo: Path, expression: object) -> tuple[str, str]:
    if not isinstance(expression, str) or expression.count("..") != 1:
        raise UsageError("review context range must be exactly START..END")
    start_token, end_token = expression.split("..", 1)
    if not start_token or not end_token:
        raise UsageError("review context range must name both START and END")
    return _resolve_commit(repo, start_token), _resolve_commit(repo, end_token)


def _range_patch(repo: Path, start: str, end: str) -> bytes:
    return _git_bytes(
        repo,
        "-c",
        "core.pager=cat",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--full-index",
        start,
        end,
        "--",
    )


def _untracked_paths(repo: Path) -> tuple[str, ...]:
    raw = _git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z")
    try:
        entries = tuple(entry.decode("utf-8") for entry in raw.split(b"\0") if entry)
    except UnicodeDecodeError as exc:
        raise UsageError("review context untracked path must be valid UTF-8") from exc
    for entry in entries:
        path = PurePosixPath(entry)
        if not entry or path.is_absolute() or ".." in path.parts:
            raise UsageError("review context Git returned an unsafe untracked path")
    return entries


def _worktree_patch(repo: Path) -> bytes:
    head = _resolve_commit(repo, "HEAD")
    patches = [
        _git_bytes(
            repo,
            "-c",
            "core.pager=cat",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "--full-index",
            head,
            "--",
        )
    ]
    total = len(patches[0])
    for relative in _untracked_paths(repo):
        patch = _git_bytes(
            repo,
            "-c",
            "core.pager=cat",
            "diff",
            "--no-index",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "--full-index",
            "--",
            "/dev/null",
            relative,
            allowed_returncodes=frozenset({0, 1}),
        )
        total += len(patch)
        if total > MAX_CHANGE_BYTES:
            raise UsageError(
                "cannot compose review context: worktree patch exceeds the "
                f"{MAX_CHANGE_BYTES}-byte limit"
            )
        patches.append(patch)
    return b"".join(patches)


def _read_input(role: str, label: str, path: Path) -> tuple[ContextInput, bytes]:
    provided = Path(path).absolute()
    # Read the exact path first.  Besides bounding the bytes, this preserves
    # the regular-file/no-symlink contract for the explicit user input before
    # we canonicalize it for the immutable manifest.
    payload = read_bounded_bytes(
        provided, label=f"review context {role} source", max_bytes=MAX_CONTEXT_SOURCE_BYTES
    )
    try:
        source = provided.resolve(strict=True)
    except OSError as exc:
        raise UsageError(
            f"cannot compose review context: {role} source is unavailable: {path}: {exc}"
        ) from exc
    if (
        read_bounded_bytes(
            source, label=f"review context {role} source", max_bytes=MAX_CONTEXT_SOURCE_BYTES
        )
        != payload
    ):
        raise UsageError(f"review context {role} source changed while it was captured: {source}")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"review context {role} source {source} must be valid UTF-8") from exc
    return ContextInput(role, label, source, _digest(payload)), payload


@dataclass(frozen=True)
class _CapturedChange:
    member: ChangeMember
    patch: bytes
    expression: str | None


def _capture_changes(
    repo: Path, *, worktree_diff: bool, ranges: tuple[str, ...]
) -> tuple[_CapturedChange, ...]:
    captured: list[_CapturedChange] = []
    total_bytes = 0

    def add(member: ChangeMember, patch: bytes, expression: str | None) -> None:
        nonlocal total_bytes
        total_bytes += len(patch)
        if total_bytes > MAX_CHANGESET_BYTES:
            raise UsageError(
                "cannot compose review context: change evidence exceeds the "
                f"{MAX_CHANGESET_BYTES}-byte total limit"
            )
        captured.append(_CapturedChange(member, patch, expression))

    if worktree_diff:
        patch = _worktree_patch(repo)
        if not patch:
            raise UsageError("review context worktree diff is empty")
        add(ChangeMember("worktree", "Working tree diff", _digest(patch)), patch, None)
    for expression in ranges:
        start, end = _resolve_range(repo, expression)
        patch = _range_patch(repo, start, end)
        add(ChangeMember("range", "Commit range", _digest(patch), start, end), patch, expression)
    if not captured:
        raise UsageError("review context requires a worktree diff or at least one commit range")
    return tuple(captured)


def _verify_input(item: ContextInput, expected: bytes) -> None:
    current = read_bounded_bytes(
        item.source_path,
        label=f"review context {item.role} source",
        max_bytes=MAX_CONTEXT_SOURCE_BYTES,
    )
    if current != expected or _digest(current) != item.digest:
        raise UsageError(
            f"review context {item.role} source changed while composing: {item.source_path}"
        )


def _verify_change(repo: Path, captured: _CapturedChange) -> None:
    member = captured.member
    if member.kind == "worktree":
        current = _worktree_patch(repo)
    else:
        assert (
            captured.expression is not None and member.start is not None and member.end is not None
        )
        start, end = _resolve_range(repo, captured.expression)
        if (start, end) != (member.start, member.end):
            raise UsageError("review context commit range changed while composing")
        current = _range_patch(repo, start, end)
    if current != captured.patch or _digest(current) != member.digest:
        raise UsageError(f"review context {member.kind} change changed while composing")


def _fenced(payload: bytes, language: str) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError("review context evidence block must be valid UTF-8") from exc
    longest = max(
        (len(line.strip()) for line in text.splitlines() if line.strip().strip("`") == ""),
        default=2,
    )
    fence = "`" * max(3, longest + 1)
    return fence + language + "\n" + text + ("" if text.endswith("\n") else "\n") + fence + "\n"


def _question(intent: ContextIntent) -> str:
    return {
        ContextIntent.ARTIFACT: "What is wrong or missing in this artifact?",
        ContextIntent.VALIDATE_PLAN: "Does this implementation satisfy the plan?",
        ContextIntent.VALIDATE_REVIEW: (
            "Are the prior review's claims supported, addressed, or contradicted by the implementation?"
        ),
        ContextIntent.VALIDATE_CHAIN: (
            "Does this implementation satisfy the plan and correctly address the review?"
        ),
    }[intent]


def _render_composite(
    manifest: ContextManifest,
    contents: Mapping[str, bytes],
    changes: tuple[_CapturedChange, ...],
) -> str:
    lines = [
        "# Review context",
        "",
        f"Review intent: {manifest.intent.value}",
        "",
        _question(manifest.intent),
        "",
        "## Manifest",
        "",
        f"- Repository: `{manifest.repository_root}`",
    ]
    for item in manifest.inputs:
        lines.append(f"- {item.role}: `{item.label}` — `{item.source_path}` — `{item.digest}`")
    for index, change in enumerate(manifest.changes, start=1):
        identity = (
            f"{change.start}..{change.end}" if change.kind == "range" else "working tree patch"
        )
        lines.append(f"- change {index}: `{change.kind}` — `{identity}` — `{change.digest}`")
    lines.extend(
        [
            "",
            "## Assessment instruction",
            "",
            "Distinguish evidence that was **not assessed** from evidence that refutes a claim; "
            "unavailable evidence is not refutation.",
        ]
    )
    for item in manifest.inputs:
        lines.extend(
            [
                "",
                f"## {item.role.title()}: {item.label}",
                "",
                _fenced(contents[item.role], "text").rstrip("\n"),
            ]
        )
    for index, captured in enumerate(changes, start=1):
        member = captured.member
        title = (
            member.label
            if member.kind == "worktree"
            else f"{member.label} ({member.start}..{member.end})"
        )
        lines.extend(
            [
                "",
                f"### Change {index}: {title}",
                "",
                _fenced(captured.patch, "diff").rstrip("\n"),
            ]
        )
    return "\n".join(lines) + "\n"


def _stage_output(path: Path, payload: bytes) -> Path:
    """Write one durable sibling temporary file without publishing it."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _destination_aliases_source(destination: Path, source: Path) -> bool:
    """Detect lexical, symlink, and hard-link aliases before any staging."""
    try:
        return destination.samefile(source)
    except OSError:
        return destination.absolute() == source


def _reject_input_output_aliases(
    output: Path, sidecar: Path, inputs: Iterable[ContextInput]
) -> None:
    for item in inputs:
        if _destination_aliases_source(output, item.source_path) or _destination_aliases_source(
            sidecar, item.source_path
        ):
            raise UsageError(
                "cannot compose review context: output or sidecar would overwrite an input: "
                f"{item.source_path}"
            )


def compose(
    *,
    repo: Path,
    out: Path,
    plan: Path | None = None,
    review: Path | None = None,
    worktree_diff: bool = False,
    ranges: Iterable[str] = (),
) -> ContextManifest:
    """Compose explicit sources, or fail without materializing either output.

    ``ranges`` is intentionally a sequence of exact ``START..END`` arguments;
    no revision expression is handed to a shell or retained in the sidecar.
    """
    if plan is None and review is None:
        raise UsageError("review context requires a plan or review input")
    if type(worktree_diff) is not bool:
        raise UsageError("review context worktree_diff must be a boolean")
    try:
        selected_ranges = tuple(ranges)
    except TypeError as exc:
        raise UsageError("review context ranges must be an iterable of strings") from exc
    if not all(isinstance(item, str) for item in selected_ranges):
        raise UsageError("review context ranges must contain only strings")
    if len(selected_ranges) + int(worktree_diff) > MAX_CHANGE_MEMBERS:
        raise UsageError(
            f"review context change set accepts at most {MAX_CHANGE_MEMBERS} worktree/range members"
        )
    root = _repository_root(Path(repo))
    output = Path(out).absolute()
    if not output.parent.is_dir():
        raise UsageError(
            f"cannot compose review context: output directory is unavailable: {output.parent}"
        )
    sidecar = output.with_suffix(output.suffix + ".json")
    captured_inputs: list[tuple[ContextInput, bytes]] = []
    if plan is not None:
        captured_inputs.append(_read_input("plan", "Implementation plan", Path(plan)))
    if review is not None:
        captured_inputs.append(_read_input("review", "Prior review", Path(review)))
    _reject_input_output_aliases(output, sidecar, (item for item, _content in captured_inputs))
    captured_changes = _capture_changes(root, worktree_diff=worktree_diff, ranges=selected_ranges)
    intent = select_intent(
        plan=plan is not None, review=review is not None, has_changes=bool(captured_changes)
    )
    manifest = ContextManifest(
        intent,
        root,
        tuple(item for item, _content in captured_inputs),
        tuple(change.member for change in captured_changes),
    )
    contents = {item.role: content for item, content in captured_inputs}
    composite = _render_composite(manifest, contents, captured_changes).encode("utf-8")

    # This is deliberately immediately before output staging: if any mutable
    # evidence changed, neither target is touched.
    for item, content in captured_inputs:
        _verify_input(item, content)
    for change in captured_changes:
        _verify_change(root, change)

    completed = ContextManifest(
        manifest.intent,
        manifest.repository_root,
        manifest.inputs,
        manifest.changes,
        _digest(composite),
    )
    sidecar_payload = (json.dumps(completed.to_dict(), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    # Stage both files before publishing either one.  The composite is the
    # authoritative artifact, so publish it first: a failed replacement must
    # not create, replace, or delete a sidecar (which could be prior evidence).
    staged_output = _stage_output(output, composite)
    try:
        staged_sidecar = _stage_output(sidecar, sidecar_payload)
    except BaseException:
        staged_output.unlink(missing_ok=True)
        raise
    try:
        staged_output.replace(output)
    except BaseException:
        staged_output.unlink(missing_ok=True)
        staged_sidecar.unlink(missing_ok=True)
        raise
    try:
        staged_sidecar.replace(sidecar)
    except BaseException:
        staged_sidecar.unlink(missing_ok=True)
        raise
    return completed
