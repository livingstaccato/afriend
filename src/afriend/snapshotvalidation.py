"""Validation helpers for untrusted snapshot metadata."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
import re
from typing import cast

from .errors import UsageError

COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")
HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _validate_commit(value: str, field: str = "commit") -> None:
    if COMMIT_RE.fullmatch(value) is None:
        raise UsageError(f"cannot resume: saved snapshot {field} must be 40 hexadecimal characters")


def _validate_source_path(value: str) -> str:
    candidate = PurePosixPath(value)
    if (
        not value
        or "\0" in value
        or candidate.is_absolute()
        or value != candidate.as_posix()
        or not candidate.parts
        or candidate == PurePosixPath(".")
        or ".." in candidate.parts
    ):
        raise UsageError(
            "cannot resume: saved snapshot source_path must be a canonical repository-relative path"
        )
    return value


def _required_string(raw: Mapping[str, object], field: str) -> str:
    if field not in raw:
        raise UsageError(f"cannot resume: saved snapshot field {field!r} is required")
    value = raw[field]
    if not isinstance(value, str) or not value:
        raise UsageError(
            f"cannot resume: saved snapshot field {field!r} must be a non-empty string"
        )
    return value


def _optional_string(raw: Mapping[str, object], field: str) -> str | None:
    if field not in raw:
        raise UsageError(f"cannot resume: saved snapshot field {field!r} is required")
    value = raw[field]
    if value is not None and not isinstance(value, str):
        raise UsageError(f"cannot resume: saved snapshot field {field!r} must be a string or null")
    if value == "":
        raise UsageError(f"cannot resume: saved snapshot field {field!r} must not be empty")
    return value


def _optional_bool(raw: Mapping[str, object], field: str) -> bool | None:
    if field not in raw:
        return None
    value = raw[field]
    if not isinstance(value, bool):
        raise UsageError(f"cannot resume: saved snapshot field {field!r} must be a boolean")
    return value


def _string_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise UsageError(f"cannot resume: saved {context} must be an object with string keys")
    return cast("Mapping[str, object]", value)
