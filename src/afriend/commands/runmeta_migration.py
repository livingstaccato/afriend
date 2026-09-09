"""Schema migrations for persisted run metadata."""

from collections.abc import Mapping
import copy
from typing import Any

from ..errors import UsageError
from . import resumevalidation

CURRENT_SCHEMA_VERSION = 4


def migrate_meta(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached current-schema view without inventing history."""
    meta = resumevalidation.bounded_metadata_copy(raw)
    version = meta.get("schema_version", 1)
    if type(version) is not int or not 1 <= version <= CURRENT_SCHEMA_VERSION:
        raise UsageError(f"unsupported run metadata schema {version!r}")
    if version < 2:
        for field in ("started_at", "finished_at", "duration_s", "exit_code", "stop_reason"):
            meta.setdefault(field, None)
        meta.setdefault("external_tool_policy", "legacy-unknown")
        meta.setdefault("attempted_calls", meta.get("spent_calls", 0))
        meta.setdefault("spent_calls", 0)
        meta.setdefault("repeat_tracker", {"last": {}, "count": {}, "disabled": {}})
        if "snapshot" not in meta:
            meta["snapshot"] = {
                "repo_root": meta.get("repo_root"),
                "commit": meta.get("snapshot_sha"),
                "tree": None,
                "artifact_path": meta.get("artifact_path", meta.get("artifact", "")),
                "artifact_hash": meta.get("artifact_hash", ""),
                "predecessor": None,
                "source_path": None,
            }
        meta.setdefault("snapshot_history", [copy.deepcopy(meta["snapshot"])])
    if version < 3:
        invocation = meta.get("invocation")
        migrated_grants: list[str] | None = None
        if isinstance(invocation, dict):
            legacy_allow = invocation.get("allow_external_tools", False)
            if type(legacy_allow) is bool:
                migrated_grants = ["*"] if legacy_allow else []
                invocation["allow_external_tools"] = migrated_grants
            elif isinstance(legacy_allow, list) and all(
                isinstance(item, str) for item in legacy_allow
            ):
                migrated_grants = sorted(legacy_allow)
                invocation["allow_external_tools"] = migrated_grants
        if migrated_grants is not None:
            meta.setdefault("external_tool_grants", migrated_grants)
    if version < 4:
        roster = meta.get("roster")
        if isinstance(roster, list):
            for entry in roster:
                if isinstance(entry, dict):
                    entry.setdefault("fresh_host_worker", False)
        _project_legacy_qualification(meta)
    meta["schema_version"] = CURRENT_SCHEMA_VERSION
    return meta


def _project_legacy_qualification(meta: dict[str, Any]) -> None:
    """Record the rule a pre-qualification run was actually admitted under.

    Judging admission before schema 4 counted independent non-host friends
    and looked no further, which is exactly `distinct-sessions`. Leaving the
    field absent is not neutral: resume fills an absent policy with the
    current default, so an upgraded binary would re-admit an old run under
    `cross-provider` -- a rule that did not exist when the run was accepted
    and that its roster was never asked to satisfy. A halted same-provider
    judging run would then refuse to resume, with no way to recover it.

    The projected value is written literally rather than read from
    `DEFAULT_QUALIFICATION_POLICY`, because it describes history. If the
    default moves again, what these runs were admitted under does not.

    Only the policy is projected, never a verdict. Whether a legacy roster
    satisfies that policy depends on which entry is the advisory host, and
    host role is assigned at resume from the current environment rather than
    stored -- so at migration time an entry that will be coerced to advisory
    is indistinguishable from an independent worker. Synthesizing a verdict
    here counted the host as a worker and admitted judging runs that must
    fail closed. Resume evaluates the roster it actually resolved, under the
    policy recorded here.
    """
    meta.setdefault("qualification_policy", "distinct-sessions")
