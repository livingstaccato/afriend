"""Tests for Windows process-tree termination via Job Objects (wingroup.py).

The Windows analogue of procgroup.py's POSIX process-group tests: a friend's
process tree must die as a unit, including a grandchild it spawned itself,
when this runner decides to stop waiting on it. Verified directly against a
real spawned tree rather than asserted from ctypes call success alone --
`TerminateJobObject` returning True proves nothing about whether the
processes it named are actually gone.
"""

import contextlib
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


def test_resume_starts_a_process_created_suspended(tmp_path):
    """The other half of closing the pre-assignment escape window: a process
    created with CREATE_SUSPENDED must not run a single instruction of its
    own until resume() is explicitly called."""
    marker = tmp_path / "ran.txt"
    proc = subprocess.Popen(
        [sys.executable, "-c", f"open(r'{marker}', 'w').write('ran')"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | wingroup.CREATE_SUSPENDED,
    )
    try:
        time.sleep(0.5)
        assert not marker.exists(), "process ran before resume() was ever called"
        wingroup.resume(proc.pid)
        proc.wait(timeout=5)
        assert marker.exists()
    finally:
        with contextlib.suppress(OSError):
            proc.kill()
        proc.wait(timeout=5)


def test_resume_on_an_already_exited_process_raises_a_catchable_error():
    """Mirrors test_assign_after_process_exit_raises_a_catchable_error:
    spawn.py's `finally: wingroup.resume(process.pid)` runs unconditionally,
    including in the (rare) case where the process has already exited by
    the time it runs, and must not crash the whole dispatch if it does."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    with pytest.raises(OSError):
        wingroup.resume(proc.pid)


def test_assign_before_resume_captures_a_grandchild_spawned_immediately_on_start():
    """Closes the escape window a code review found: assign() only pulls in
    a process's FUTURE descendants, and a process resumed the ordinary way
    (not created suspended) can spawn a child of its own before its caller
    finishes OpenProcess+AssignProcessToJobObject -- that child would never
    be a job member. Creating the process with CREATE_SUSPENDED and calling
    assign() before resume() closes this structurally: the parent has
    executed no instructions -- including the one that spawns its own child
    -- until resume() runs, by which point it is already a member."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _PARENT_SPAWNS_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | wingroup.CREATE_SUSPENDED,
    )
    job = wingroup.create_job()
    try:
        wingroup.assign(job, proc.pid)
        wingroup.resume(proc.pid)
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


def test_terminate_polls_membership_until_it_clears_within_the_grace_window(monkeypatch):
    """TerminateJobObject only *initiates* termination -- a member's rundown
    completes asynchronously, so a single immediate membership check (the
    old behavior) would misreport routine, still-finishing rundown as a
    suspected orphan. `_assigned_process_count` is stubbed to simulate that:
    it reports a member present for the first two checks and gone on the
    third, and terminate() must keep polling rather than trusting the first
    (nonzero) reading."""
    job = wingroup.create_job()
    try:
        calls = {"n": 0}

        def fake_count(_handle: int) -> int:
            calls["n"] += 1
            return 1 if calls["n"] < 3 else 0

        monkeypatch.setattr(wingroup, "_assigned_process_count", fake_count)

        orphans_suspected = wingroup.terminate(job, grace_seconds=2.0)

        assert orphans_suspected is False
        assert calls["n"] >= 3
    finally:
        wingroup.close(job)


def test_terminate_reports_a_suspected_orphan_if_membership_never_clears(monkeypatch):
    """The other side of the same fix: polling must still give up and report
    a suspected orphan once grace_seconds elapses, rather than polling
    forever. Asserts the wait was actually observed too, not just the
    return value -- a regression back to a single immediate check would
    also return True here without ever waiting out the window."""
    job = wingroup.create_job()
    try:
        monkeypatch.setattr(wingroup, "_assigned_process_count", lambda _handle: 1)

        started = time.monotonic()
        orphans_suspected = wingroup.terminate(job, grace_seconds=0.2)
        elapsed = time.monotonic() - started

        assert orphans_suspected is True
        assert elapsed >= 0.15
    finally:
        wingroup.close(job)
