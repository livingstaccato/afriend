"""Evidence-admission policies for a resolved friend roster.

The projection deliberately talks about requested model identities, not the
provider backend that ultimately answered.  A provider CLI can receive an
exact model request without being able to attest to the backend identity.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .adapters import FriendSpec
from .errors import UsageError

QUALIFICATION_POLICIES = ("cross-provider", "distinct-sessions", "distinct-models")
DEFAULT_QUALIFICATION_POLICY = "cross-provider"
CONCRETE_MODEL_SOURCES = frozenset(
    {"invocation", "explicit-friend", "roster", "provider-setting", "adapter-default"}
)
# A concrete *source* is not the same as a concrete *identity*. `MODEL_RE`
# admits any of these words, and `--friend codex:red:fast` records them as
# explicitly requested, so without this set `distinct-models` would admit two
# labels and the report would call them two exact model identities. Matched
# whole and casefolded, so a real id that merely contains one of these words
# (`gpt-5.3-codex-spark`) is unaffected.
NON_IDENTITY_MODEL_LABELS = frozenset(
    {"fast", "thorough", "default", "unknown", "auto", "inherit", "none", "latest"}
)


@dataclass(frozen=True)
class Qualification:
    """A small, persisted-safe account of the evidence rule a roster meets."""

    policy: str
    qualified: bool
    qualifying_names: tuple[str, ...]
    provider_families: tuple[str, ...]
    reason: str | None


def restore_frozen_qualification(resume_meta: object) -> Qualification | None:
    """Rebuild a run's recorded qualification from its frozen metadata.

    Returns None when there is nothing frozen to replay -- a fresh run, or a
    run predating the field that migration did not project -- so the caller
    falls back to deciding admission normally.

    Resume treats run.json as hostile input, so this validates shape and
    policy rather than trusting it: a payload that is not a dict, omits a
    field, carries a wrong type, or names a policy this version does not
    know is refused outright. What it deliberately does not do is re-derive
    `qualified` from the roster. That value is the record of a decision
    already made, and recomputing it is the whole defect this exists to fix.
    """
    if not isinstance(resume_meta, dict):
        return None
    payload = resume_meta.get("qualification")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise UsageError("cannot resume: saved qualification must be an object")
    policy = payload.get("policy")
    if policy not in QUALIFICATION_POLICIES:
        raise UsageError(
            f"cannot resume: saved qualification policy {policy!r} is not one of "
            f"{list(QUALIFICATION_POLICIES)}"
        )
    qualified = payload.get("qualified")
    if not isinstance(qualified, bool):
        raise UsageError("cannot resume: saved qualification.qualified must be a boolean")
    names = payload.get("qualifying_names", [])
    families = payload.get("provider_families", [])
    for field, value in (("qualifying_names", names), ("provider_families", families)):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise UsageError(
                f"cannot resume: saved qualification.{field} must be a list of strings"
            )
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise UsageError("cannot resume: saved qualification.reason must be a string or null")
    return Qualification(policy, qualified, tuple(names), tuple(families), reason)


def qualify(specs: Sequence[FriendSpec], policy: str) -> Qualification:
    """Evaluate one policy without modifying the roster or dispatching work."""
    if policy not in QUALIFICATION_POLICIES:
        raise UsageError(
            f"unknown qualification policy {policy!r}; choose one of {list(QUALIFICATION_POLICIES)}"
        )
    workers = [spec for spec in specs if spec.independent and not spec.host_self_review]
    names = tuple(spec.name for spec in workers)
    families = tuple(dict.fromkeys(spec.cli for spec in workers))
    if policy == "cross-provider":
        qualified = len(families) >= 2
        reason = None if qualified else _family_reason(families)
    elif policy == "distinct-sessions":
        qualified = len(names) >= 2
        reason = None if qualified else "fewer than two fresh worker invocations"
    else:
        labelled = sorted(
            {
                spec.model
                for spec in workers
                if spec.model is not None and spec.model.casefold() in NON_IDENTITY_MODEL_LABELS
            }
        )
        concrete = [
            spec
            for spec in workers
            if spec.model is not None
            and spec.model_source in CONCRETE_MODEL_SOURCES
            and spec.model.casefold() not in NON_IDENTITY_MODEL_LABELS
        ]
        models = {spec.model for spec in concrete}
        qualified = len(concrete) >= 2 and len(models) >= 2
        if qualified:
            reason = None
        elif labelled:
            reason = (
                f"{', '.join(labelled)} names a selection label, not an exact model "
                "identity; distinct-models needs two different requested model ids"
            )
        else:
            reason = "two distinct exact model requests are required"
    return Qualification(policy, qualified, names, families, reason)


def _family_reason(families: tuple[str, ...]) -> str:
    if not families:
        return "no qualifying worker providers"
    if len(families) == 1:
        return f"one provider family: {families[0]}"
    return "fewer than two provider families"
