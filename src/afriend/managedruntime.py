"""Preserve Pi's Node selection when confinement redirects generic state."""

import os
from pathlib import Path
import stat


def _uses_managed_node(executable: str | None) -> bool:
    """Recognize the measured managed launcher's Node-selection contract.

    An npm/manual Pi can coexist with a managed install. Its mere presence
    must not change the interpreter chosen by the selected executable.
    Inspect only a bounded launcher prefix; never execute it to discover
    its runtime. Opening follows PATH symlinks to the actual entrypoint.
    """
    if executable is None:
        return False
    try:
        descriptor = os.open(executable, os.O_RDONLY | os.O_NONBLOCK)
        try:
            # which() can accept an executable FIFO. Inspect the opened
            # object, avoiding both a blocking open and a stat/open race.
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return False
            launcher = os.read(descriptor, 16384)
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return (
        b"pi_node_bin=${XDG_DATA_HOME:-$HOME/.local/share}/pi-node/current/bin" in launcher
        and b"PATH=$pi_node_bin:$PATH" in launcher
    )


def pi_node_reads(env: dict[str, str], cwd: Path, executable: str | None = None) -> tuple[str, ...]:
    """Pin Node using the actual child environment, returning literal read grants.

    The managed POSIX launcher prepends its own Node before consulting PATH.
    Save that choice before XDG_DATA_HOME moves into private state, only
    when the selected executable actually uses that launcher contract. Only
    absolute PATH entries are retained: a review checkout must not supply the
    interpreter through an empty or relative entry. A system Node needs only
    its executable; the managed distribution also carries sibling libraries.
    """
    if os.name != "posix":
        return ()
    entries = [
        entry
        for entry in env.get("PATH", os.defpath).split(os.pathsep)
        if Path(entry).is_absolute()
    ]
    # Empty PATH is one implicit cwd entry to execvp, not an empty search.
    env["PATH"] = os.pathsep.join(entries) or os.devnull
    data_home = env.get("XDG_DATA_HOME")
    if not data_home and env.get("HOME"):
        data_home = str(Path(env["HOME"]) / ".local/share")
    if data_home and _uses_managed_node(executable):
        runtime = Path(data_home) / "pi-node/current"
        if not runtime.is_absolute():
            runtime = cwd / runtime
        node = runtime / "bin/node"
        if node.is_file() and os.access(node, os.X_OK):
            env["PATH"] = os.pathsep.join((str(node.parent), *entries))
            return str(node), str(runtime)
    for entry in entries:
        node = Path(entry) / "node"
        if node.is_file() and os.access(node, os.X_OK):
            return (str(node),)
    return ()
