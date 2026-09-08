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


@dataclass(frozen=True)
class Qualification:
    """A small, persisted-safe account of the evidence rule a roster meets."""

    policy: str
    qualified: bool
    qualifying_names: tuple[str, ...]
    provider_families: tuple[str, ...]
    reason: str | None


def qualify(specs: Sequence[FriendSpec], policy: str) -> Qualification:
    """Evaluate one policy without modifying the roster or dispatching work."""
    if policy not in QUALIFICATION_POLICIES:
        raise UsageError(
            f"unknown qualification policy {policy!r}; choose one of {list(QUALIFICATION_POLICIES)}"
        )
    workers = [spec for spec in specs if spec.independent and not spec.host_self_review]
    names = tuple(spec.name for spec in workers)
    # ``fake`` is a test-only transport with no provider family.  Preserve
    # existing end-to-end fixtures by giving each fake invocation a synthetic
    # family; this value can never occur in a real discovered roster.
    families = tuple(
        dict.fromkeys(spec.name if spec.cli == "fake" else spec.cli for spec in workers)
    )
    if policy == "cross-provider":
        qualified = len(families) >= 2
        reason = None if qualified else _family_reason(families)
    elif policy == "distinct-sessions":
        qualified = len(names) >= 2
        reason = None if qualified else "fewer than two fresh worker invocations"
    else:
        concrete = [
            spec
            for spec in workers
            if spec.model is not None and spec.model_source in CONCRETE_MODEL_SOURCES
        ]
        models = {spec.model for spec in concrete}
        qualified = len(concrete) >= 2 and len(models) >= 2
        reason = None if qualified else "two distinct exact model requests are required"
    return Qualification(policy, qualified, names, families, reason)


def _family_reason(families: tuple[str, ...]) -> str:
    if not families:
        return "no qualifying worker providers"
    if len(families) == 1:
        return f"one provider family: {families[0]}"
    return "fewer than two provider families"
