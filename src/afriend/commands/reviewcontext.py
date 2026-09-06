"""Freeze and validate the narrowly-scoped composer receipt used by ``run``."""

from __future__ import annotations

import hashlib
from pathlib import Path
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


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def capture_review_context(
    artifact: Path, artifact_text: str
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
    if manifest.output_sha256 != _sha256(artifact_text.encode("utf-8")):
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
    artifact_text = read_artifact_text(artifact)
    return artifact_text, capture_review_context(artifact, artifact_text)


def resume_review_context(
    store: RunStore, meta: dict[str, Any], frozen: Path
) -> dict[str, str] | None:
    """Validate a copied composer receipt against the frozen artifact only."""
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
        if has_copied_manifest or read_artifact_text(frozen).split("\n", 1)[0] == COMPOSER_MARKER:
            raise UsageError(
                "cannot resume: frozen review context evidence is missing review_context metadata"
            )
        return None
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
