"""Freeze and validate the narrowly-scoped composer receipt used by ``run``."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any

from ..errors import UsageError
from ..jsonio import MAX_JSON_FILE_BYTES, decode_json_object, read_bounded_bytes
from ..reviewcontext import COMPOSER_MARKER, ContextManifest
from ..runstore import RunStore

REVIEW_CONTEXT_MANIFEST_PATH = "review-context.json"


def read_artifact_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"artifact must be valid UTF-8: {path}") from exc
    except OSError as exc:
        raise UsageError(f"cannot read artifact {path}: {exc}") from exc


def read_artifact_bytes_and_text(path: Path) -> tuple[bytes, str]:
    """One bounded read, returning both forms.

    The digest check needs the artifact's exact bytes and everything else
    needs its newline-translated text, and these used to be two separate
    reads of the same file: `read_artifact_text` followed by a bare
    `artifact.read_bytes()`. That second read had neither of the protections
    this module applies to the sidecar beside it -- no size bound, no
    regular-file check, no OSError handling, so a failure escaped as a bare
    traceback out of cli.main, which catches only AfError. It also doubled
    peak memory, since the text was still held.

    Worse, being a second read made the digest a claim about bytes that may
    no longer be the ones dispatched: a file rewritten between the two reads
    was verified in one form and sent in the other. That is the TOCTOU
    `read_bounded_bytes` re-fstats to prevent, reintroduced one line below a
    call that uses it.

    Deliberately NOT `read_bounded_bytes`: that refuses symlinks, and an
    artifact is allowed to be one -- `commands/environment.py` documents the
    rule that a symlinked artifact picks its repository from the invocation
    path rather than the link target. So this opens once and fstats the
    descriptor it actually got, which is the same TOCTOU property without
    the symlink refusal.

    The 32 MiB ceiling is new on this path; neither previous read had one.
    It is what `spawn.MAX_OUTPUT_BYTES` already allows a friend to produce,
    and an artifact above it could not be dispatched into a prompt anyway,
    so it refuses only inputs that were going to fail later and names the
    limit when it does.
    """
    if Path(path).is_dir():
        # Windows refuses to open a directory at all, which would otherwise
        # read as a permission problem rather than the wrong kind of path.
        raise UsageError(f"artifact {path} must be a regular file")
    try:
        # O_BINARY: Windows opens descriptors in text mode by default and
        # would strip every \r before the digest sees the bytes.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        raise UsageError(f"cannot read artifact {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise UsageError(f"artifact {path} must be a regular file")
        if info.st_size > MAX_JSON_FILE_BYTES:
            raise UsageError(f"artifact {path} exceeds the {MAX_JSON_FILE_BYTES}-byte limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = os.read(descriptor, 1 << 20)
            except OSError as exc:
                raise UsageError(f"cannot read artifact {path}: {exc}") from exc
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_JSON_FILE_BYTES:
                raise UsageError(f"artifact {path} exceeds the {MAX_JSON_FILE_BYTES}-byte limit")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"artifact must be valid UTF-8: {path}") from exc
    # Match Path.read_text()'s universal-newline mode, which every existing
    # consumer of the text form already assumes.
    return payload, decoded.replace("\r\n", "\n").replace("\r", "\n")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def capture_review_context(
    artifact: Path, artifact_text: str, artifact_bytes: bytes | None = None
) -> tuple[dict[str, str], bytes] | None:
    """Capture the exact composer receipt adjacent to a marked artifact."""
    if artifact_text.split("\n", 1)[0] != COMPOSER_MARKER:
        return None
    sidecar = artifact.with_suffix(artifact.suffix + ".json")
    try:
        sidecar.lstat()
    except FileNotFoundError:
        raise UsageError(
            f"marked review context artifact requires review context manifest {sidecar}"
        ) from None
    except OSError as exc:
        raise UsageError(f"cannot inspect review context manifest {sidecar}: {exc}") from exc
    payload = read_bounded_bytes(sidecar, label="review context manifest")
    manifest = ContextManifest.from_dict(
        decode_json_object(payload, path=sidecar, label="review context manifest")
    )
    # The artifact's bytes, not its newline-translated text: compose()
    # digests exactly what it wrote, while read_artifact_text() goes through
    # universal-newline mode and rewrites CRLF to LF. A CRLF-authored plan --
    # or any CRLF file caught in the captured diff -- therefore produced an
    # artifact that `afriend context` published and `afriend run` immediately
    # refused. resume_review_context (below) already compares read_bytes().
    # The caller's own read, when it has one: re-reading here would verify
    # bytes that are not necessarily the bytes about to be dispatched.
    payload_bytes = artifact_bytes if artifact_bytes is not None else artifact.read_bytes()
    if manifest.output_sha256 != _sha256(payload_bytes):
        raise UsageError(
            "review context manifest output_sha256 does not match the artifact it accompanies"
        )
    return (
        {
            "intent": manifest.intent.value,
            "manifest_digest": _sha256(payload),
            "manifest_path": REVIEW_CONTEXT_MANIFEST_PATH,
        },
        payload,
    )


def capture_artifact_input(
    artifact: Path,
) -> tuple[str, tuple[dict[str, str], bytes] | None]:
    """Decode an artifact and capture any marked composer receipt before setup."""
    artifact_bytes, artifact_text = read_artifact_bytes_and_text(artifact)
    return artifact_text, capture_review_context(artifact, artifact_text, artifact_bytes)


def resume_review_context(
    store: RunStore, meta: dict[str, Any], frozen: Path
) -> dict[str, str] | None:
    """Validate a copied composer receipt against the frozen artifact only."""
    has_marker = read_artifact_text(frozen).split("\n", 1)[0] == COMPOSER_MARKER
    copied_manifest = store.run_dir / REVIEW_CONTEXT_MANIFEST_PATH
    try:
        copied_manifest.lstat()
        has_copied_manifest = True
    except FileNotFoundError:
        has_copied_manifest = False
    except OSError as exc:
        raise UsageError(
            f"cannot resume: cannot inspect copied review context manifest: {exc}"
        ) from exc
    if "review_context" not in meta:
        if has_copied_manifest or has_marker:
            raise UsageError(
                "cannot resume: frozen review context evidence is missing review_context metadata"
            )
        return None
    if not has_marker:
        raise UsageError("cannot resume: review_context metadata requires a frozen composer marker")
    value = meta["review_context"]
    expected = {"intent", "manifest_digest", "manifest_path"}
    if type(value) is not dict or set(value) != expected:
        raise UsageError("cannot resume: saved review_context has an invalid shape")
    context = value
    intent = context["intent"]
    manifest_digest = context["manifest_digest"]
    manifest_path = context["manifest_path"]
    if not all(isinstance(item, str) for item in (intent, manifest_digest, manifest_path)):
        raise UsageError("cannot resume: saved review_context fields must be strings")
    if manifest_path != REVIEW_CONTEXT_MANIFEST_PATH:
        raise UsageError("cannot resume: saved review_context manifest path is invalid")
    try:
        payload = store.read_owned_bytes(
            store.run_dir / manifest_path, max_bytes=MAX_JSON_FILE_BYTES
        )
    except OSError as exc:
        raise UsageError(
            f"cannot resume: copied review context manifest is unavailable or unsafe: {exc}"
        ) from exc
    if _sha256(payload) != manifest_digest:
        raise UsageError("cannot resume: copied review context manifest digest does not match")
    manifest = ContextManifest.from_dict(
        decode_json_object(
            payload,
            path=store.run_dir / manifest_path,
            label="copied review context manifest",
        )
    )
    if manifest.intent.value != intent:
        raise UsageError("cannot resume: copied review context manifest intent does not match")
    if manifest.output_sha256 != _sha256(frozen.read_bytes()):
        raise UsageError(
            "cannot resume: copied review context manifest does not bind frozen artifact"
        )
    return {
        "intent": intent,
        "manifest_digest": manifest_digest,
        "manifest_path": manifest_path,
    }


def doc_scope_note(review_context: dict[str, str]) -> str:
    return (
        "review context implementation validation was not assessed because no repository "
        f"snapshot could be established (intent: {review_context['intent']})."
    )
