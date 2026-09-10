"""Validation for adapter TOML, kept out of adapters.py's line budget.

Every function here refuses a MALFORMED DECLARATION at load time rather than
letting it become an argv or a sandbox policy. The recurring defect these
exist for is a scalar written where a list belongs: TOML accepts it, Python
iterates it, and `list("--sandbox")` is nine single characters that nothing
downstream can tell apart from one flag. For a path list the same slip is a
filesystem grant -- `~` and `/` resolve to $HOME and the root -- while the
run record still reports the friend OS-confined.

Refused with the file named, never defaulted: one bad adapter file must say
which file it is, because raising out of `load_adapters` disables every
adapter in the directory with no way to tell which one caused it.
"""

from pathlib import Path

from .errors import UsageError
from .trust import MODEL_RE

_MAX_CAPABILITY_PROBE_ARGS = 32
_MAX_CAPABILITY_PROBE_ARG_CHARS = 256
_MAX_CAPABILITY_PROBE_MARKERS = 16
_SAFE_CAPABILITY_PROBE_ACTIONS = {"--help", "--version", "help", "version"}


def _string_list(path: Path, field: str, value: object, *, nonempty: bool = False) -> list[str]:
    """Refuse a scalar where a list of strings belongs.

    `list("--sandbox")` is nine single characters, not one flag, and nothing
    downstream can tell the difference. For a sandbox path list it is worse
    than noise: `_add_declared` expanduser/resolves each member, so the
    characters `~` and `/` become $HOME and the filesystem root -- one
    missing pair of brackets grants a friend the whole filesystem while the
    run record still reports it OS-confined.

    `nonempty` is for the PATH lists, one bracket pair from the same grant:
    `""` resolves to the process working directory, so `write = [""]` -- an
    unfinished placeholder -- hands the invoking repository over read-write
    while the record still reports the friend confined. Every sibling path or
    name validator already requires `isinstance(value, str) and value`.

    OFF for argv lists, where an empty member is a legitimate flag VALUE:
    agy's `base_argv` ends `"--print", ""`, and that empty string is what
    satisfies `--print`.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UsageError(f"{path}: {field} must be a list of strings")
    if nonempty and not all(value):
        raise UsageError(f"{path}: {field} must not contain an empty string")
    return list(value)


def _string_table(path: Path, field: str, value: object) -> dict[str, list[str]]:
    """Refuse a scalar where a table of string lists belongs.

    `_string_list`'s defect one field over: `effort = "high"` reached
    `.items()` and raised `AttributeError` out of `load_adapters`, naming no
    file and disabling every adapter. The values are argv fragments, so a
    scalar level would be shredded into characters just as `readonly_argv`
    was.
    """
    if not isinstance(value, dict):
        raise UsageError(f"{path}: {field} must be a table")
    return {key: _string_list(path, f"{field}.{key}", item) for key, item in value.items()}


def _validate_capability_probe(path: Path, probe_argv: list[str], probe_markers: list[str]) -> None:
    """Keep adapter probes bounded and structurally incapable of a model call."""
    if (
        len(probe_argv) > _MAX_CAPABILITY_PROBE_ARGS
        or any(
            len(value) > _MAX_CAPABILITY_PROBE_ARG_CHARS
            or any(character in value for character in ("\x00", "\n", "\r"))
            for value in probe_argv
        )
        or probe_argv[-1] not in _SAFE_CAPABILITY_PROBE_ACTIONS
    ):
        raise UsageError(f"{path}: deny capability probe must be bounded and end in help/version")
    if len(probe_markers) > _MAX_CAPABILITY_PROBE_MARKERS or any(
        len(marker) > _MAX_CAPABILITY_PROBE_ARG_CHARS
        or any(character in marker for character in ("\x00", "\n", "\r"))
        for marker in probe_markers
    ):
        raise UsageError(f"{path}: deny capability probe markers must be bounded")


def _validate_default_model(path: Path, value: object) -> str | None:
    """Accept the optional static adapter model only when it is safe to pass."""
    if value is None:
        return None
    if not isinstance(value, str) or MODEL_RE.fullmatch(value) is None:
        raise UsageError(
            f"{path}: default_model must be null or match {MODEL_RE.pattern!r}; got {value!r}"
        )
    return value
