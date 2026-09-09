"""The single accepted shape of persisted run metadata.

There is one schema. A run.json either matches it or is refused; nothing is
upgraded on read. Migration existed to carry runs written by older releases
forward, and every path it added was a second definition of what a run is --
one for the current shape and one for each shape that came before, each with
its own defaults, coercions and reconstructions. That is where the bugs
lived: a policy silently filled from the wrong default, a verdict
synthesized from a roster whose host role was not yet known.

Refusing is honest and recoverable. The run directory is plain text, and a
report, ledger and claims file remain readable without the CLI.
"""

from collections.abc import Mapping
from typing import Any

from ..errors import UsageError
from . import resumevalidation

CURRENT_SCHEMA_VERSION = 4


def validated_meta(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached copy, or refuse metadata this version cannot read."""
    meta = resumevalidation.bounded_metadata_copy(raw)
    version = meta.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        raise UsageError(
            f"run metadata schema {version!r} is not readable by this version, "
            f"which reads schema {CURRENT_SCHEMA_VERSION} only. The run directory "
            "is plain text: report.md, claims.jsonl and the round transcripts "
            "remain readable without the CLI."
        )
    return meta
