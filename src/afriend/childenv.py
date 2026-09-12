"""What an executable friend process may see in its environment -- §12.2.

Found by running this tool against its own sandbox: the filesystem policy
was careful and the environment was not filtered at all, so a friend
inherited every secret already exported in the runner's shell. A
prompt-injected friend could read another service's token without touching a
single forbidden path -- the confinement boundary had a hole straight through
the middle of it.

**Applied to every executable friend, independently of filesystem
confinement.** A CLI's read-only mode limits writes, not reads from its own
environment. HTTP friends have no child process and therefore no child
environment to filter.

**An allowlist, like everything else here.** A denylist of "things that look
like secrets" is direction-blind in the same way §13's rejected flag
denylist was: it misses every variable nobody thought of, and those are
exactly the ones worth protecting.

The hard part is that a friend's OWN credentials usually arrive by
environment too, so a filter that guesses wrong breaks authentication with no
useful error. That is why the pass list is per-adapter and declared, never
inferred -- and why `--pass-env` exists for the operator who knows something
this project does not.
"""

from collections.abc import Mapping
import os
from pathlib import Path

from .secureio import secure_mkdir

# Variables any process needs to start and behave sanely. None of these
# carries a credential; each was included because dropping it changes
# behaviour rather than exposure.
BASE_PASS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TZ",
    # A CLI that respects XDG needs to find its own config, and those paths
    # are already in the filesystem allowlist -- withholding the variable
    # would only make it look in the wrong place.
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    # Node and Python runtimes: the CLIs here are mostly one or the other.
    "NODE_PATH",
    "NVM_DIR",
    "PYTHONPATH",
    "PYTHONHOME",
    # Windows equivalents of the above, plus variables Windows networking
    # itself depends on to start at all. Found by running this tool against
    # a real installed codex on Windows: withholding SystemRoot made DNS
    # resolution fail inside the child with "os error 11003" (WSANO_DATA)
    # on every request, even though the exact same command run directly in
    # the operator's own shell reached the network fine -- Winsock
    # initialization needs SystemRoot to load its own system DLLs, which a
    # POSIX-shaped allowlist had no reason to know about. None of these
    # carries a credential either; PATHEXT is what lets Windows execute a
    # CLI shipped as a `.cmd`/`.bat` shim at all.
    "SystemRoot",
    "windir",
    "USERPROFILE",
    "USERNAME",
    "USERDOMAIN",
    "APPDATA",
    "LOCALAPPDATA",
    "ALLUSERSPROFILE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "COMSPEC",
    "PATHEXT",
    "COMPUTERNAME",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)


def private_root_for(workdir: Path) -> Path:
    """Where a friend's scratch and state go, given its working directory.

    A sibling, never a child. For a repo-scope friend the working directory
    IS the git worktree of the code under review, so scratch written inside
    it dirties the tree the snapshot exists to keep pristine.

    Not the parent either: that is the round's isolation root, which holds
    every other friend's tree. Granting one friend write access to it is the
    mistake the original `$TMPDIR` grant made, one level down.

    A function rather than an expression at the call site because the choice
    is the fix -- an earlier version passed the working directory straight
    in, and nothing named the decision or could test it.
    """
    return workdir.parent / f"{workdir.name}.private"


def private_dirs(private_root: Path) -> dict[str, str]:
    """Environment pointing a friend's scratch and state at `private_root`.

    A CLI that keeps a cache in `$TMPDIR` or a log under `$XDG_DATA_HOME`
    otherwise needs those real locations, and granting them is worse than it
    sounds: `$TMPDIR` holds every other friend's isolation tree and every
    other same-user temporary file, and a home state directory outlives the
    run. opencode needed both until it was given these instead -- it now
    writes its log inside a directory that is deleted when the round ends,
    and reads nothing outside it.

    **`private_root` is a sibling of the friend's working directory, never
    inside it.** The earlier version wrote `.af-scratch/` and `.af-data/`
    into the working directory, which for a repo-scope friend IS the git
    worktree of the code under review -- so the runner dirtied the tree it
    had just snapshotted to keep pristine. A friend running `git status` to
    orient itself saw two untracked directories that were not in the commit
    it was reviewing, and the CLI's own config landed among the files it was
    asked to critique. Raised as a deadlocked claim; the layout settles it.

    The caller places `private_root` under the round's isolation root, so it
    is torn down with everything else and needs no cleanup of its own.

    The directories are created here because a CLI that finds `$TMPDIR`
    missing falls back to the real one, which is the hole this closes.
    """
    scratch = private_root / "tmp"
    data = private_root / "state"
    for path in (scratch, data):
        secure_mkdir(path, parents=True, exist_ok=True, root=private_root.parent)
    return {
        "TMPDIR": str(scratch),
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "XDG_CACHE_HOME": str(scratch),
        "XDG_DATA_HOME": str(data),
        "XDG_STATE_HOME": str(data),
        "XDG_CONFIG_HOME": str(data),
    }


def build(
    adapter_pass: tuple[str, ...] = (),
    operator_pass: tuple[str, ...] = (),
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The filtered environment an executable friend process receives.

    Only variables that are BOTH allowed and actually set are returned:
    exporting an empty value for an unset variable would tell a CLI that a
    setting exists when it does not, which is its own source of confusing
    failures.

    Matched case-insensitively. Windows environment variable names are
    case-insensitive by OS convention -- found live on this runtime:
    `SystemRoot` in `BASE_PASS` never matched, because the real variable
    is stored as `SYSTEMROOT`, and a plain case-sensitive set membership
    check (unlike `name in os.environ`, which Windows' own `os.environ`
    special-cases) does not know that. Withholding it silently broke DNS
    resolution inside every confined child on Windows -- Winsock needs it
    to load its own system DLLs -- so a critique that reached the network
    fine when run directly failed inside every dispatched friend instead.
    Case-insensitive matching is harmless on POSIX, where a real process
    exporting two names differing only in case is not a case this project
    needs to support.
    """
    source = os.environ if environ is None else environ
    allowed = {name.upper() for name in (*BASE_PASS, *adapter_pass, *operator_pass)}
    return {name: value for name, value in source.items() if name.upper() in allowed}


def withheld(
    adapter_pass: tuple[str, ...] = (),
    operator_pass: tuple[str, ...] = (),
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Names dropped from the child's environment, for the run record.

    Names only, never values: this list goes into run.json and report.md,
    and writing a secret into the run directory to report that it was
    protected would be its own leak.
    """
    source = os.environ if environ is None else environ
    allowed = {name.upper() for name in (*BASE_PASS, *adapter_pass, *operator_pass)}
    return sorted(name for name in source if name.upper() not in allowed)
