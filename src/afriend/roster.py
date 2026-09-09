"""Decide which friends run, on which model, under which lens.

Self-exclusion drops the host's (cli, model) pair rather than the whole
binary. Blanket per-binary exclusion would be wrong: a CLI judging a spec its
own model authored, under a different lens and effort level, is sometimes
exactly what you want.
"""

from collections.abc import Callable, Mapping
from dataclasses import replace
import shutil
from typing import Any

from .adapters import Adapter, FriendSpec, ModelSource
from .authority import AuthorityPolicy, enforce as enforce_authority
from .errors import NoFriendsError, UsageError
from .providerconfig import ProviderPolicy
from .readiness import (
    HOST_ENV_MARKERS as HOST_ENV_MARKERS,
    NO_HTTP_DISCOVERY_ENV as NO_HTTP_DISCOVERY_ENV,
    ReadinessState,
    assess_all,
    detect_host as detect_host,
    effective_host_inclusion,
)
from .trust import validate_roster_entry

# opencode exposes no read-only mode, so it may not read the repository
# without an explicit opt-in from the operator.
NO_READONLY_DEFAULT_SCOPE = "doc"
DEGRADED_MODES = frozenset({"report"})
DEFAULT_TIMEOUT = 900


def apply_capacity(
    specs: list[FriendSpec], max_friends: int | None
) -> tuple[list[FriendSpec], list[FriendSpec]]:
    if max_friends is None:
        return specs, []
    if max_friends <= 0:
        raise UsageError("max_friends must be a positive integer")
    return specs[:max_friends], specs[max_friends:]


def mark_host_role(specs: list[FriendSpec], host: str | None) -> list[FriendSpec]:
    """Mark every selected instance of the orchestrating provider advisory."""
    if host is None:
        return specs
    return [
        (
            spec
            if spec.cli != host or spec.fresh_host_worker
            else replace(spec, independent=False, host_self_review=True)
        )
        for spec in specs
    ]


def _selected_model(
    explicit_model: str | None,
    explicit_source: ModelSource,
    provider_model: str | None,
    adapter_model: str | None,
) -> tuple[str | None, ModelSource]:
    """Apply the non-invocation model layers without truthiness shortcuts."""
    if explicit_model is not None:
        return explicit_model, explicit_source
    if provider_model is not None:
        return provider_model, "provider-setting"
    if adapter_model is not None:
        return adapter_model, "adapter-default"
    return None, "cli-default"


# Set to any non-empty value to keep HTTP friends out of auto-discovery
# without stopping the server. `--friend ollama:lens:model` still works --
# this only governs whether a reachable endpoint is *enlisted automatically*.
# Someone running ollama for unrelated reasons should not find it silently
# joining every run.
def discover_clis(
    registry: dict[str, Adapter],
    which: Callable[[str], str | None] = shutil.which,
    probe: Callable[[str], bool] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """A wider projection of the canonical readiness assessment.

    Reachable HTTP providers without a model remain visible here because
    `afriend init` writes them as editable placeholders. Automatic run
    selection is stricter and consumes only READY rows directly.
    """
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env=env,
        which=which,
        probe=probe,
        include_self=True,
    )
    eligible = {ReadinessState.READY, ReadinessState.REACHABLE_UNCONFIGURED}
    return [name for name, row in rows.items() if row.state in eligible]


def resolve(
    registry: dict[str, Adapter],
    lenses: list[str],
    env: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    include_self: bool | None = None,
    overrides: list[dict[str, Any]] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    probe: Callable[[str], bool] | None = None,
    provider_policy: ProviderPolicy | None = None,
    max_friends: int | None = None,
    min_workers: int = 1,
    host_provider: str | None = None,
    enforce: Callable[[Adapter], object] | None = None,
    authority_policy: AuthorityPolicy | None = None,
) -> list[FriendSpec]:
    host = detect_host(env, host_provider=host_provider)
    effective_include_self = effective_host_inclusion(host, include_self)
    # NOTE for whoever wires a --roster file flag through `overrides`:
    # `if overrides:` (not `if overrides is not None:`) means an explicit,
    # caller-supplied *empty* list is indistinguishable from "no overrides
    # given" and silently falls through to full auto-discovery below. If a
    # roster file can legitimately name zero friends, check for that case
    # before calling resolve() and raise NoFriendsError yourself -- do not
    # rely on this function to do it. (Task 12's cli.py never triggers this
    # at all: its --friend flag path builds FriendSpecs directly and never
    # calls resolve(overrides=...) -- see cli._specs_from_flags's own
    # docstring.)
    override_specs: list[FriendSpec] | None = None
    if overrides:
        override_specs = []
        seen_names: set[str] = set()
        for _index, entry in enumerate(overrides):
            validate_roster_entry(entry)
            name = entry["name"]
            if name in seen_names:
                # Friend names become path components under the run directory
                # (see ids.py); two entries sharing a name would silently
                # clobber each other's output instead of raising.
                raise UsageError(
                    f"duplicate friend name {name!r} in roster overrides: "
                    "names must be unique because they become output paths"
                )
            seen_names.add(name)
            adapter = registry.get(entry["cli"])
            if adapter is None:
                # NOTE for whoever wires a --roster file flag through
                # `overrides`: this raises NoFriendsError (exit 3) for an
                # unknown cli, but a config typo is a usage error, not "no
                # friends available" -- UsageError (exit 2) fits better.
                # Left unchanged here since fixing it would change this
                # function's behavior for existing callers/tests; Task 12's
                # own --friend flag path (cli._specs_from_flags) raises
                # UsageError directly instead of going through this branch
                # at all, for exactly this reason.
                raise NoFriendsError(f"unknown cli in roster: {entry['cli']!r}")
            default_scope = "repo" if adapter.is_readonly else NO_READONLY_DEFAULT_SCOPE
            override_specs.append(
                FriendSpec(
                    name=name,
                    cli=entry["cli"],
                    lens=entry["lens"],
                    model=entry.get("model"),
                    effort=entry.get("effort"),
                    scope=entry.get("scope", default_scope),
                    timeout=entry.get("timeout", timeout),
                    model_source="roster" if entry.get("model") is not None else "cli-default",
                )
            )

    # An explicitly named roster is still subject to provider authority.
    # Decide that from declarations before readiness performs any executable
    # or endpoint probes, and surface PolicyError directly rather than
    # degrading a security refusal into a generic "no friends" outcome.
    if override_specs is not None and authority_policy is not None:
        for spec in override_specs:
            enforce_authority(registry[spec.cli], authority_policy.for_provider(spec.cli))

    readiness = assess_all(
        registry,
        provider_policy or ProviderPolicy({}),
        env=env,
        which=which,
        probe=probe,
        include_self=effective_include_self,
        host_provider=host_provider,
        enforce=enforce,
        authority_policy=authority_policy,
    )
    if override_specs is not None:
        specs = []
        rejected = []
        for spec in override_specs:
            row = readiness[spec.cli]
            adapter_default = registry[spec.cli].default_model
            roster_model_makes_ready = row.state is ReadinessState.REACHABLE_UNCONFIGURED and (
                spec.model is not None or adapter_default is not None
            )
            if not row.ready and not roster_model_makes_ready:
                rejected.append(f"{spec.name} ({spec.cli}): {row.reason}")
                continue
            model, source = _selected_model(
                spec.model,
                spec.model_source,
                row.model,
                adapter_default,
            )
            specs.append(replace(spec, model=model, model_source=source))
        if not specs:
            raise NoFriendsError(
                "no usable friends from roster after readiness filtering: " + "; ".join(rejected)
            )
        selected, _dropped = apply_capacity(specs, max_friends)
        return mark_host_role(selected, host)

    available = [
        name
        for name, row in readiness.items()
        if row.ready
        or (
            row.state is ReadinessState.REACHABLE_UNCONFIGURED
            and registry[name].default_model is not None
        )
    ]
    if not available:
        raise NoFriendsError(
            "no usable friends found. Install a second agent CLI "
            "(codex, agy, opencode) or pass --include-self."
        )
    if not lenses:
        # available is non-empty here, so lenses[index % len(lenses)] below
        # would otherwise raise ZeroDivisionError instead of a clean,
        # actionable error.
        raise UsageError(
            "no lenses configured: at least one lens is required to assign to discovered friends."
        )

    pairings = [(cli, lenses[index % len(lenses)]) for index, cli in enumerate(available)]
    # This loop iterates over PROVIDERS, so a machine with one ready provider
    # discovered exactly one friend however many lenses were configured --
    # and every judging mode then refused before creating a run directory.
    # `distinct-sessions` accepts two sessions of one provider as evidence,
    # but nothing could BUILD such a roster: only hand-written --friend flags
    # reached it. `min_workers` is how a caller says the run needs two
    # sessions and its policy will accept same-provider ones.
    #
    # Only the sole-provider case fans out. Two providers already supply two
    # sessions, and that pair is the stronger roster -- a third session would
    # spend a friend to weaken the average. Extra sessions take further
    # lenses, never a repeated one: names are lens-derived and become run
    # directory paths (ids.py), so a repeat would collide rather than
    # disagree.
    if len(available) == 1:
        sole = available[0]
        for lens in lenses[1:]:
            if len(pairings) >= min_workers:
                break
            pairings.append((sole, lens))
    specs = []
    for cli, lens in pairings:
        adapter = registry[cli]
        scope = "repo" if adapter.is_readonly else NO_READONLY_DEFAULT_SCOPE
        model, source = _selected_model(
            None,
            "cli-default",
            readiness[cli].model,
            adapter.default_model,
        )
        specs.append(
            FriendSpec(
                name=f"{cli}-{lens}",
                cli=cli,
                lens=lens,
                model=model,
                effort=None,
                scope=scope,
                timeout=timeout,
                model_source=source,
            )
        )
    selected, _dropped = apply_capacity(specs, max_friends)
    return mark_host_role(selected, host)
