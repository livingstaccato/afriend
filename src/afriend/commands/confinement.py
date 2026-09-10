"""What a run records about friends the OS has to confine -- §12.2, §12.3.

Split from commands/run.py for the line cap. It is also one concern: every
weakened guarantee a confined friend introduces belongs in the artifact a
human reads, not only in the code that decided it.
"""

import argparse

from .. import childenv, sandbox
from ..adapters import Adapter, FriendSpec


def confinement_downgrades(
    args: argparse.Namespace,
    specs: list[FriendSpec],
    registry: dict[str, Adapter],
    downgrades: list[str],
) -> list[str]:
    """Append confinement notes to `downgrades`; return withheld env names.

    These notes describe what can be known before dispatch. The report's
    per-friend `os_confined` field is derived later from whether dispatch
    actually produced a sandbox wrapper; it is deliberately not inferred
    here from a read-only flag or requested scope.

    The returned list is the run's record that secrets were kept from
    friends, so it must describe what dispatch will actually do
    (`childenv.build(adapter.env_pass, pass_env)`, for every exec friend).
    Computed any other way it is worse than no record: a crossexam of this
    file found `--pass-env` being passed in `withheld`'s *adapter* slot, so
    every name an adapter declares in its own `pass` list -- six API keys,
    for opencode -- was reported as withheld while being handed to the
    child.

    Every exec friend, not only the OS-confined ones. Environment filtering
    used to be gated on the same condition as filesystem confinement, so the
    three CLIs that confine themselves inherited everything; the record
    followed that gate and named only the others.
    """
    execs = [
        s
        for s in specs
        if s.cli in registry and registry[s.cli].transport != "http" and s.cli != "fake"
    ]
    unconfined = [s for s in execs if registry[s.cli].needs_os_confinement]
    env_withheld: list[str] = []
    if execs:
        # Per friend, from the same inputs dispatch uses. A name counts as
        # withheld only if NO friend received it; one that some adapter's own
        # pass list lets through is named separately rather than being folded
        # into a list that claims it was kept back.
        per_friend = {
            s.name: set(childenv.withheld(registry[s.cli].env_pass, tuple(args.pass_env)))
            for s in execs
        }
        kept_from_all = set.intersection(*per_friend.values())
        # Names only, never values: this list reaches run.json and report.md,
        # and writing a secret into the run directory to report that it was
        # protected would be its own leak.
        env_withheld = sorted(kept_from_all)
        passed_to_some = sorted(set.union(*per_friend.values()) - kept_from_all)
        if env_withheld:
            downgrades.append(
                f"{len(env_withheld)} environment variable(s) were withheld from "
                f"every friend this run dispatches ({', '.join(s.name for s in execs)}); "
                "names are recorded, values never are. Pass --pass-env VAR if "
                "a friend needs one."
            )
        if passed_to_some:
            downgrades.append(
                "these variables were withheld from some friends but passed to "
                "others, because an adapter declares them in its own pass list: "
                f"{', '.join(passed_to_some)}. They are NOT in this run's withheld "
                "record."
            )
    mechanism = sandbox.detect() if unconfined else None
    if unconfined and mechanism is None:
        # No mechanism, so these friends get no FILESYSTEM confinement. Their
        # environment is still filtered -- that is not what a sandbox does.
        downgrades.append(
            "no OS confinement mechanism is available here, so the filesystem of "
            + ", ".join(s.name for s in unconfined)
            + " is not confined: each can read anything this user can. Their "
            "environment is still filtered."
        )
    # Scope is chosen before dispatch; confinement is decided per run. The
    # three sites that grant repo scope ask `is_readonly`, and for agy that
    # property is true only BECAUSE of its `[sandbox]` block -- so with no
    # mechanism the friend gets a repo-scope worktree of the code under
    # review on the strength of a protection this same run records as
    # `write_protected: false`. Switching those sites to
    # `needs_os_confinement` would drop agy and codex to doc scope on every
    # host, including the ones where `readonly_workdir` genuinely engages, so
    # the mismatch is recorded here -- where the run knows what engaged --
    # rather than repaired by narrowing scope everywhere.
    scope_mismatch = [
        s
        for s in unconfined
        if s.scope == "repo" and registry[s.cli].sandbox_readonly_workdir and mechanism is None
    ]
    if scope_mismatch:
        downgrades.append(
            "these friends were granted repo scope because their adapter declares a "
            "read-only mode, but that write protection IS the OS sandbox and none "
            "engaged: "
            + ", ".join(s.name for s in scope_mismatch)
            + ". Each received a writable git worktree of the code under review, and "
            "this run records its write protection as withdrawn."
        )
    if unconfined and args.allow_unsandboxed_friend and mechanism is None:
        downgrades.append(
            "--allow-unsandboxed-friend was passed as fallback only when no OS confinement "
            "mechanism is available; it never disables an available bwrap or sandbox-exec: "
            + ", ".join(s.name for s in unconfined)
            + " may run with no OS confinement and retain same-user filesystem "
            "read access. The artifact under "
            "review is untrusted text; a friend that follows an instruction "
            "inside it can read anything this user can."
        )
    return env_withheld
