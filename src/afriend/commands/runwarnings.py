"""Operator-visible warnings emitted during run orchestration."""

from pathlib import Path
import sys

from .environment import snapshot_scope_downgrade_note


def warn_doc_scope(artifact: Path, downgrades: list[str], warning_seen: bool) -> bool:
    """Emit the automatic doc-scope warning once when that downgrade applies."""
    if warning_seen:
        return True
    note = snapshot_scope_downgrade_note(artifact.name)
    if note not in downgrades:
        return False
    print(
        "afriend: warning: doc scope only -- no repository was detected for "
        f"the artifact '{artifact.name}'. Friends can only read the artifact "
        "text, not repository code. Place the artifact file inside the "
        "repository you want reviewed to get full scope.",
        file=sys.stderr,
        flush=True,
    )
    return True
