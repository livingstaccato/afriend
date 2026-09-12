"""Tests for Windows process-tree termination via Job Objects (wingroup.py).

The Windows analogue of procgroup.py's POSIX process-group tests: a friend's
process tree must die as a unit, including a grandchild it spawned itself,
when this runner decides to stop waiting on it. Verified directly against a
real spawned tree rather than asserted from ctypes call success alone --
`TerminateJobObject` returning True proves nothing about whether the
processes it named are actually gone.
"""

import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.windows_only(reason="wingroup.py is the Windows-only process-tree kill path"),
    pytest.mark.process,
]

if sys.platform == "win32":
    from afriend import wingroup


def _is_running(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
    ).stdout
    return str(pid) in out


_PARENT_SPAWNS_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(p.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def test_terminate_kills_both_parent_and_grandchild():
    """A friend's own child (unwaited-on) must die alongside it -- the same
    property procgroup._terminate_group verifies for POSIX process groups."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _PARENT_SPAWNS_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    job = wingroup.create_job()
    try:
        wingroup.assign(job, proc.pid)
        grandchild_pid = int(proc.stdout.readline().strip())
        time.sleep(0.3)
        assert _is_running(proc.pid)
        assert _is_running(grandchild_pid)

        orphans_suspected = wingroup.terminate(job)

        assert orphans_suspected is False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and (
            _is_running(proc.pid) or _is_running(grandchild_pid)
        ):
            time.sleep(0.1)
        assert not _is_running(proc.pid)
        assert not _is_running(grandchild_pid)
    finally:
        wingroup.close(job)
        proc.wait(timeout=5)


def test_terminate_on_an_already_exited_process_reports_no_orphan():
    """A friend that finished on its own before the sweep runs must not be
    reported as a suspected orphan -- mirrors procgroup._terminate_group's
    fast no-op path for a group with nothing left in it."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    job = wingroup.create_job()
    try:
        wingroup.assign(job, proc.pid)
        proc.wait(timeout=5)
        orphans_suspected = wingroup.terminate(job)
        assert orphans_suspected is False
    finally:
        wingroup.close(job)


def test_assign_after_process_exit_raises_a_catchable_error():
    """spawn.py must not crash the whole dispatch if assignment loses a race
    against a process that exits immediately; OpenProcess on a dead pid
    fails, and that failure must be a plain OSError, not something exotic."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    job = wingroup.create_job()
    try:
        with pytest.raises(OSError):
            wingroup.assign(job, proc.pid)
    finally:
        wingroup.close(job)
