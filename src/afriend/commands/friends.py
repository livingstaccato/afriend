"""Deciding who a run's friends are -- spec §10.1, §13.

Split out of commands/run.py for the line cap. It is also a genuinely
separate decision from running them: four sources can contribute, and §10.1
orders them strongest-last.

    1. the friend's own config   <- default: emit no model/effort flags
    2. --preset
    3. a roster file
    4. --friend

Each layer only fills what the one above left unset, so an operator can keep
a roster and still override a single run from the command line.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil

from .. import providerconfig, rosterfile
from ..adapters import Adapter, FriendSpec, ModelSource, validate_roster_uniqueness
from ..authority import DENY_ALL, AuthorityPolicy, enforce
from ..cliargs import _specs_from_flags
from ..errors import NoFriendsError, UsageError
from ..ids import validate_friend_name
from ..presets import default_preset, effort_for, no_effort_note, unverifiable_note
from ..prompt import available_lenses
from ..qualification import (
    DEFAULT_QUALIFICATION_POLICY,
    Qualification,
    qualify,
    restore_frozen_qualification,
)
from ..readiness import (
    DenyProbeResult,
    ReadinessState,
    assess_all,
    detect_host,
    effective_host_inclusion,
)
from ..roster import DEGRADED_MODES, apply_capacity, mark_host_role, resolve


@dataclass
class ResolvedRoster:
    specs: list[FriendSpec]
    preset: str
    source: str | None = None
    detected_host: str | None = None
    effective_include_self: bool | None = None
    qualification: Qualification | None = None


def _selected_model(
    invocation_model: str | None,
    explicit_model: str | None,
    explicit_source: ModelSource,
    provider_model: str | None,
    adapter_model: str | None,
) -> tuple[str | None, ModelSource]:
    """Resolve one model selection with its immutable source."""
    if invocation_model is not None:
        return invocation_model, "invocation"
    if explicit_model is not None:
        return explicit_model, explicit_source
    if provider_model is not None:
        return provider_model, "provider-setting"
    if adapter_model is not None:
        return adapter_model, "adapter-default"
    return None, "cli-default"


def validate_resume_capabilities(
    specs: list[FriendSpec],
    registry: dict[str, Adapter],
    authority_policy: AuthorityPolicy,
    *,
    which: Callable[[str], str | None] = shutil.which,
    capability_probe: Callable[[Adapter, str], DenyProbeResult] | None = None,
) -> None:
    """Revalidate mutable executable authority for a frozen resume roster.

    Identity, model and ordering remain frozen. Provider enablement, host
    exclusion and capacity are discovery policy and deliberately do not run
    again. The executable and its deny flags are mutable local facts, though,
    so a resume must prove them again before opening the run for mutation.
    """
    names = dict.fromkeys(spec.cli for spec in specs if spec.cli != "fake")
    if not names:
        return
    selected: dict[str, Adapter] = {}
    for name in names:
        adapter = registry.get(name)
        if adapter is None:
            raise UsageError(f"unknown cli in saved roster: {name!r}")
        selected[name] = adapter
    rows = assess_all(
        selected,
        providerconfig.ProviderPolicy({}),
        env=os.environ,
        which=which,
        include_self=True,
        authority_policy=authority_policy,
        selection_policy=False,
        capability_probe=capability_probe,
    )
    models = {spec.cli: spec.model for spec in specs}
    for name, row in rows.items():
        configured_http = (
            row.state is ReadinessState.REACHABLE_UNCONFIGURED and models[name] is not None
        )
        if not row.ready and not configured_http:
            raise UsageError(
                f"cannot resume: saved provider {name!r} is {row.state.value}: {row.reason}"
            )


def _validated_selection_args(
    args: argparse.Namespace, registry: dict[str, Adapter]
) -> tuple[set[str], set[str], str | None, list[str]]:
    """Validate selection controls without assessing current providers."""
    enabled = set(getattr(args, "enable_provider", []))
    disabled = set(getattr(args, "disable_provider", []))
    contradictory = enabled & disabled
    if contradictory:
        raise UsageError(
            f"provider(s) {sorted(contradictory)} were passed to both "
            "--enable-provider and --disable-provider"
        )
    provider_unknown = (enabled | disabled) - set(registry)
    if provider_unknown:
        raise UsageError(
            f"unknown provider(s) {sorted(provider_unknown)}; known: {sorted(registry)}"
        )
    host_provider = getattr(args, "host_provider", None)
    if host_provider is not None and host_provider not in registry:
        raise UsageError(f"unknown --host-provider {host_provider!r}; known: {sorted(registry)}")

    lenses = available_lenses()
    if getattr(args, "lens", None):
        known = set(lenses)
        unknown = [name for name in args.lens if name not in known]
        if unknown:
            raise UsageError(f"unknown lens(es) {sorted(unknown)}; available: {sorted(known)}")
        lenses = list(args.lens)
    return enabled, disabled, host_provider, lenses


SAME_PROVIDER_POLICY = "distinct-sessions"
QUORUM_WORKERS = 2


def _sessions_needed(args: argparse.Namespace) -> int:
    """How many worker sessions discovery should build.

    One per provider is the rule everywhere except the case that made this
    function necessary: a judging mode whose policy accepts two sessions of
    the SAME provider. Discovery iterates over providers, so on a machine
    with one ready provider it built one friend and every judging mode
    refused -- `distinct-sessions` was a policy nothing could satisfy except
    hand-written --friend flags.

    `report` is excluded deliberately. It applies no evidence rule, so a
    second session would double the cost of every single-provider run to
    satisfy a policy that is not being consulted.
    """
    if _policy(args) != SAME_PROVIDER_POLICY or args.mode in DEGRADED_MODES:
        return 1
    # Capacity is applied after discovery, so a session built beyond
    # `--max-friends` is constructed only to be trimmed -- and the note about
    # the roster would then describe friends that no longer exist.
    capacity = getattr(args, "max_friends", None)
    if isinstance(capacity, int) and capacity < QUORUM_WORKERS:
        return max(capacity, 1)
    return QUORUM_WORKERS


def _note_same_provider_quorum(specs: list[FriendSpec], downgrades: list[str], policy: str) -> None:
    """Say when a quorum came from one provider.

    Reachable is not the same as equivalent: sessions of one CLI share an
    account and a failure mode. Silence would let the report read as
    disagreement between independent reviewers.

    Called once, from `roster_for_run`, beside the qualification it
    describes. Wiring it into discovery instead left the documented
    workaround -- `--friend codex:a --friend codex:b` -- and every roster
    file undisclosed, because both replace discovery entirely.

    The predicate is policy-agnostic (several workers, one family), so the
    text takes the policy being applied rather than naming one: under
    `distinct-models` these sessions do NOT share a model, and saying so
    would be false.
    """
    workers = [spec for spec in specs if spec.independent and not spec.host_self_review]
    families = {spec.cli for spec in workers}
    if len(workers) < QUORUM_WORKERS or len(families) != 1:
        return
    shared = "an account and a failure mode"
    if policy == SAME_PROVIDER_POLICY:
        shared = "an account, a model and a failure mode"
    note = (
        f"all {len(workers)} judging sessions run on the same provider "
        f"({families.pop()}) under the {policy!r} policy; they share {shared}, so "
        "agreement between them is weaker evidence than agreement across providers"
    )
    if note not in downgrades:
        downgrades.append(note)


def _policy(args: argparse.Namespace) -> str:
    """The qualification policy this run is being built and judged under.

    One reader. Resolving it separately where the roster is built and where
    it is admitted let the two disagree, which would produce a refusal that
    discovery had just been told to satisfy.
    """
    return getattr(args, "qualification_policy", None) or DEFAULT_QUALIFICATION_POLICY


def resolve_friends(
    args: argparse.Namespace,
    registry: dict[str, Adapter],
    fake_cmd: list[str] | None,
    downgrades: list[str],
    authority_policy: AuthorityPolicy | None = None,
) -> ResolvedRoster:
    """Apply §10.1's precedence and return the roster a run will use."""
    if authority_policy is None:
        authority_policy = AuthorityPolicy.from_grants(
            getattr(args, "allow_external_tools", []), registry
        )
    # §10.1's precedence, strongest last: adapter defaults, then --preset,
    # then a roster file, then --friend. Each layer only fills what the one
    # above it left unset, so an operator can keep a roster and still
    # override one run from the command line.
    preset = args.preset or default_preset(args.mode)
    roster_source: str | None = None
    enabled, disabled, host_provider, lenses = _validated_selection_args(args, registry)
    host = detect_host(os.environ, host_provider=host_provider)
    requested_self = getattr(args, "include_self", None)
    include_host = effective_host_inclusion(host, requested_self)
    provider_policy = providerconfig.load(registry, os.environ)
    if enabled or disabled:
        settings = dict(provider_policy.providers)
        for name in enabled | disabled:
            current = provider_policy.setting(name)
            settings[name] = providerconfig.ProviderSetting(
                enabled=name in enabled,
                model=current.model,
            )
        provider_policy = providerconfig.ProviderPolicy(settings)
    invocation_model = getattr(args, "model", None)
    if invocation_model is not None:
        # Invocation flags are §10.1's strongest layer. Apply the global
        # model before readiness so a reachable HTTP provider is not rejected
        # as unconfigured before that stronger layer gets a chance to fill it.
        provider_policy = providerconfig.ProviderPolicy(
            {
                name: providerconfig.ProviderSetting(
                    enabled=provider_policy.setting(name).enabled,
                    model=invocation_model,
                )
                for name in registry
            }
        )

    # §8.1: --lens restricts which lenses discovery assigns. Unknown names
    # are refused rather than silently ignored -- a typo would otherwise
    # quietly shrink the run to whichever lenses happened to match.
    explicit = bool(args.friend)
    if getattr(args, "fresh_host_worker", False) and not explicit:
        # Only the --friend branch below marks a spec fresh, so on the
        # discovery and roster-file paths the flag was silently discarded and
        # the host stayed advisory -- the opposite of what it asks for. The
        # run then failed its own qualification policy ("fewer than two fresh
        # worker invocations") with no remedy mentioning the flag that was
        # thrown away. Refusing here says so at the point of the mistake.
        raise UsageError(
            "--fresh-host-worker requires an explicit matching --friend: it marks "
            "a named friend as a separately launched worker, and neither "
            "discovery nor a roster file selects one."
        )
    if explicit:
        specs = _specs_from_flags(args.friend, args.timeout, registry, bool(fake_cmd))
        if getattr(args, "fresh_host_worker", False):
            if host is None or not any(spec.cli == host for spec in specs):
                raise UsageError(
                    "--fresh-host-worker requires --host-provider and an explicit matching --friend"
                )
            specs = [
                replace(spec, fresh_host_worker=True) if spec.cli == host else spec
                for spec in specs
            ]
        if host is not None and not include_host:
            # This filter exists to drop the *advisory* host, so it must not
            # reach a worker that was just marked fresh: that spec is a
            # separately launched execution, not the invoking harness.
            specs = [spec for spec in specs if spec.cli != host or spec.fresh_host_worker]
        if args.roster:
            downgrades.append(
                "both --friend and --roster were given; --friend replaces the "
                "roster entirely (§10.1), so the roster file was not read."
            )
        if getattr(args, "lens", None):
            # --lens restricts what DISCOVERY assigns; --friend names each
            # lens itself, so there is nothing left for it to restrict. It
            # used to be parsed, validated against the lens directory, and
            # then dropped in silence -- the same courtesy --roster gets
            # above is owed here.
            downgrades.append(
                "--lens was given with --friend; each --friend names its own "
                "lens, so --lens selected nothing and was not applied."
            )
    else:
        # §13: an explicitly named roster may live anywhere. Only the trusted
        # user-level path is ever picked up on its own -- a cloned repo must
        # not be able to choose who reviews it.
        roster_path = Path(args.roster) if args.roster else rosterfile.discover()
        if roster_path is not None:
            if getattr(args, "lens", None):
                # The roster file names each friend's lens explicitly, exactly
                # like --friend, so --lens has nothing to restrict here
                # either. Passing available_lenses() below (rather than the
                # filtered list) was correct; saying nothing about it was not.
                downgrades.append(
                    "--lens was given with a roster file; the roster names each "
                    "friend's lens, so --lens selected nothing and was not applied."
                )
            specs = resolve(
                registry,
                available_lenses(),
                os.environ,
                shutil.which,
                include_self=args.include_self,
                overrides=rosterfile.load(roster_path),
                timeout=args.timeout,
                provider_policy=provider_policy,
                host_provider=host_provider,
                authority_policy=authority_policy,
                notes=downgrades,
            )
            roster_source = str(roster_path)
        else:
            specs = resolve(
                registry,
                lenses,
                os.environ,
                shutil.which,
                include_self=args.include_self,
                timeout=args.timeout,
                provider_policy=provider_policy,
                host_provider=host_provider,
                authority_policy=authority_policy,
                min_workers=_sessions_needed(args),
            )
    if not specs:
        raise NoFriendsError(f"no usable friends for mode {args.mode!r}")
    if explicit:
        # Naming a friend overrides automatic enabled/host/discovery
        # selection, not whether that friend can actually be dispatched.
        # Assess every explicitly named provider exactly once before capacity:
        # an unavailable prefix must not hide a ready friend later in the
        # operator's ordered roster.
        explicit_names = dict.fromkeys(spec.cli for spec in specs if spec.cli != "fake")
        readiness = assess_all(
            {name: registry[name] for name in explicit_names},
            provider_policy,
            env=os.environ,
            which=shutil.which,
            include_self=True,
            authority_policy=authority_policy,
            selection_policy=False,
        )
        checked: list[FriendSpec] = []
        rejected: list[str] = []
        for spec in specs:
            if spec.cli == "fake":
                checked.append(spec)
                continue
            row = readiness[spec.cli]
            effective_model, model_source = _selected_model(
                invocation_model,
                spec.model,
                "explicit-friend",
                row.model,
                registry[spec.cli].default_model,
            )
            configured_http = (
                row.state is ReadinessState.REACHABLE_UNCONFIGURED and effective_model is not None
            )
            if not row.ready and not configured_http:
                if row.state is ReadinessState.POLICY_BLOCKED:
                    raise UsageError(row.reason)
                rejected.append(f"{spec.name} ({spec.cli}): {row.reason}")
                continue
            checked.append(replace(spec, model=effective_model, model_source=model_source))
        if rejected and not checked:
            raise NoFriendsError("explicit friend preflight failed: " + "; ".join(rejected))
        if rejected:
            downgrades.append(
                "explicit friend preflight skipped unavailable entries: " + "; ".join(rejected)
            )
        specs = checked
    # Capacity applies to the dispatch-ready roster. A discarded or unready
    # friend never runs, so it cannot consume capacity or contribute preset
    # limitations to the surviving run.
    limit = getattr(args, "max_friends", None)
    specs, dropped_specs = apply_capacity(specs, limit)
    if dropped_specs:
        dropped = [spec.name for spec in dropped_specs]
        downgrades.append(
            f"--max-friends={limit} dropped {dropped}; this run has fewer "
            "independent judges than the roster named."
        )
    # The preset fills effort only where nothing stronger set it, so a roster
    # entry's own `effort` wins -- that is what makes preset weaker than
    # roster in §10.1's order rather than merely different.
    if preset != "inherit":
        filled = []
        for spec in specs:
            adapter = registry.get(spec.cli)
            if adapter is None or spec.effort is not None:
                filled.append(spec)
                continue
            for note in (
                unverifiable_note(preset, adapter),
                no_effort_note(preset, adapter),
            ):
                if note and note not in downgrades:
                    downgrades.append(note)
            filled.append(replace(spec, effort=effort_for(preset, adapter)))
        specs = filled
    # §10.1 layer 4: invocation flags outrank the roster and the preset.
    model = getattr(args, "model", None)
    effort = getattr(args, "effort", None)
    if model is not None or effort is not None:
        specs = [
            replace(
                s,
                model=model if model is not None else s.model,
                effort=effort if effort is not None else s.effort,
                model_source="invocation" if model is not None else s.model_source,
            )
            for s in specs
        ]

    # Explicit --friend values bypass discovery, but not host-role audit.
    # Apply this once more to every path so roster files and discovery stay
    # idempotent while explicit selections receive the same marking.
    specs = mark_host_role(specs, host)

    validate_roster_uniqueness(specs, judging=args.mode != "report")
    for spec in specs:
        if spec.cli != "fake":
            enforce(registry[spec.cli], authority_policy.for_provider(spec.cli))
    return ResolvedRoster(
        specs=specs,
        preset=preset,
        source=roster_source,
        detected_host=host,
        effective_include_self=include_host,
    )


def _effective_lenses(args: argparse.Namespace, registry: dict[str, Adapter]) -> list[str]:
    """The lenses THIS run may assign, not every lens on disk.

    `_remedies` used `available_lenses()` and so recommended a policy whose
    roster this run could not build: under `--lens assumptions`, or a review
    profile naming one lens, there is no second lens for a second session to
    be named with.
    """
    try:
        return _validated_selection_args(args, registry)[3]
    except UsageError:
        return list(available_lenses())


def _remedies(qualification: Qualification, lenses: list[str], resumed: bool) -> str:
    """What an operator can actually do about this refusal.

    The reported case: a host with one ready provider was told to add a
    qualifying worker or drop to `--mode report`, and worked out on its own
    that naming two friends of the one provider it had would satisfy
    `distinct-sessions`. That policy ships, validates and is documented; the
    refusal simply never named it, while being constructed with the policy in
    hand.

    Every option here has to be one that changes the outcome:

    - A resumed run replays a frozen qualification, so the policy flag is
      ignored by design and the roster cannot gain a friend. Both ordinary
      remedies are inert, and printing them tells the operator to do two
      things that provably do nothing.
    - `distinct-sessions` and `distinct-models` do not ask for a second
      PROVIDER, so naming one is wrong advice under two of the three
      policies.
    - A second session needs a second lens to be named with, because friend
      names are lens-derived and become run-directory paths. Under a
      restricted `--lens` (or a profile's `lenses` list) the lens count is
      the real blocker, and the policy flag leads to an identical refusal.
    """
    if resumed:
        return (
            "A resumed run replays the qualification its ledger recorded, so neither the "
            "roster nor --qualification-policy can change it. Start a new run to review "
            "this artifact under a different policy or roster."
        )
    remedies = []
    if qualification.policy == DEFAULT_QUALIFICATION_POLICY:
        remedies.append("add a friend on a second provider")
    else:
        remedies.append("add a friend that satisfies this policy")
    if qualification.policy != SAME_PROVIDER_POLICY and qualification.qualifying_names:
        if len(lenses) >= QUORUM_WORKERS:
            remedies.append(
                f"pass --qualification-policy {SAME_PROVIDER_POLICY} to accept "
                f"{QUORUM_WORKERS} sessions of one provider as evidence (weaker: they share "
                "an account, a model and a failure mode)"
            )
        else:
            remedies.append(
                f"configure a second lens -- {SAME_PROVIDER_POLICY} would accept "
                f"{QUORUM_WORKERS} sessions of one provider, but each needs its own lens "
                f"to be named with and this run has {len(lenses)}"
            )
    remedies.append("use --mode report for a single reviewer's opinion")
    return "Options: " + "; ".join(remedies) + "."


def roster_for_run(
    args: argparse.Namespace,
    registry: dict[str, Adapter],
    fake_cmd: list[str] | None,
    downgrades: list[str],
    authority_policy: AuthorityPolicy = DENY_ALL,
) -> tuple[ResolvedRoster, list[FriendSpec]]:
    """The roster this run will actually dispatch, and the refusals that
    come with it.

    Separated from `cmd_run` when it crossed the then-current line cap. It
    is also one concern: which friends run, decided in one place, including
    the two rules that can stop a run before anything is spent -- §8.3's
    minimum and a resumed run's recorded roster.
    """
    # A resumed run judges with the roster its ledger was written against.
    resume_roster = getattr(args, "_resume_roster", None)
    resumed = resume_roster is not None
    if resume_roster is not None:
        _validated_selection_args(args, registry)
        specs = list(resume_roster)
        resume_meta = getattr(args, "_resume_meta", {}) or {}
        resolved = ResolvedRoster(
            specs=specs,
            preset=args.preset or default_preset(args.mode),
            source=resume_meta.get("roster_source"),
            detected_host=resume_meta.get("detected_host"),
            effective_include_self=resume_meta.get("effective_include_self"),
        )
        validate_resume_capabilities(specs, registry, authority_policy)
    else:
        resolved = resolve_friends(args, registry, fake_cmd, downgrades, authority_policy)
        specs = resolved.specs

    # The concrete final roster, whether freshly resolved or restored from
    # run.json, owns output paths and (in judging modes) ledger identities.
    # Frozen resume data must not bypass either invariant.
    validate_roster_uniqueness(specs, judging=args.mode != "report")
    for spec in specs:
        validate_friend_name(spec.name)
        if spec.cli != "fake":
            adapter = registry.get(spec.cli)
            if adapter is None and registry:
                raise UsageError(f"unknown cli in saved roster: {spec.cli!r}")
            if adapter is not None:
                enforce(adapter, authority_policy.for_provider(spec.cli))

    # A resumed run replays a decision that was already made. Re-running
    # admission would make acceptance a property of the current binary
    # rather than of the run: a default that moved, or a refined predicate,
    # would refuse a run that its own metadata records as qualified, and
    # there would be no way to recover it. The frozen payload is authority
    # for history; `restore_frozen_qualification` still refuses a payload
    # that is malformed or names a policy this version does not know.
    frozen = restore_frozen_qualification(getattr(args, "_resume_meta", None))
    qualification = frozen or qualify(specs, _policy(args))
    resolved.qualification = qualification
    # Beside the qualification it describes, and after capacity trimming, so
    # it speaks about the roster that will actually run.
    _note_same_provider_quorum(specs, downgrades, qualification.policy)
    if not qualification.qualified:
        # §8.3. --friend REPLACES the roster rather than augmenting
        # discovery (see cliargs._specs_from_flags), so a single --friend
        # flag -- or discovery itself resolving to one friend -- produces a
        # run that cannot cross-examine anything.
        #
        # `report` is allowed to run and say so. Every other mode is
        # refused, because "cross-examination with one participant is a
        # different and weaker thing wearing the same name": with no judge
        # independent of any claim, a `gate` run settles nothing, blocks on
        # nothing, and exits 0 -- CI reads "gate clear" from a run that
        # structurally could not check anything. This was a downgrade note
        # for every mode until a crossexam of this file found the exit-0
        # gate and the DEGRADED_MODES constant that was wired to nothing.
        # A replayed verdict is still enforced. Replay fixes *which* rule is
        # applied -- the one the run recorded, not the current default -- but
        # a run whose own metadata says it never qualified must not become
        # judgeable by being resumed. A roster holding only an advisory host
        # is exactly that case, and admitting it would rebuild the exit-0
        # gate this file already documents.
        if args.mode not in DEGRADED_MODES:
            names = ", ".join(qualification.qualifying_names) or "none"
            families = ", ".join(qualification.provider_families) or "none"
            raise NoFriendsError(
                f"roster does not satisfy qualification policy {qualification.policy!r}: "
                f"workers ({names}); provider families ({families}); "
                f"{qualification.reason}. Judging needs at least two independent "
                f"friends under the selected policy. "
                f"{_remedies(qualification, _effective_lenses(args, registry), resumed)}"
            )
        if len(specs) == 1:
            downgrades.append(
                f"only one friend ({specs[0].name}) resolved for this run; "
                "cross-examination needs at least two independent friends, so "
                "this report reflects a single reviewer's opinion, not "
                "disagreement between several."
            )
    return resolved, specs
