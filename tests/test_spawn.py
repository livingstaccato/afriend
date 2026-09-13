import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from afriend import spawn
from afriend.envelopes import Envelope

pytestmark = pytest.mark.process


FAKE = str(Path(__file__).resolve().parent / "fake_friend.py")

_POSIX_ONLY = pytest.mark.posix_only(
    reason="tests a POSIX-specific escape/signal mechanism (os.setsid(), "
    "SIGTERM-then-SIGKILL escalation) with no Windows equivalent -- Job "
    "Objects (wingroup.py) structurally prevent the escape rather than "
    "tolerating it, and TerminateJobObject has no graceful mode to escalate "
    "from. See tests/test_wingroup.py for the Windows-appropriate coverage.",
)
_WINDOWS_ONLY = pytest.mark.windows_only(
    reason="exercises wingroup.py's Job Object cleanup path directly"
)

# A friend that answers with a valid json_path-envelope payload and then
# hangs -- the same "answer, then don't exit" shape agy's own docstring in
# envelopes.py documents as its normal behavior. Used to exercise the
# `answered=True` path in run_process, which none of the fake_friend.py
# modes above reach on their own: fake_friend's own findings/verdicts
# payload has no envelope wired to it in these tests, so `early_envelope`
# would stay None and the wait loop would only ever exit via a natural
# process exit or a timeout.
_ANSWER_THEN_HANG = (
    "import json, sys, time\nprint(json.dumps({'response': 'ok'}), flush=True)\ntime.sleep(600)\n"
)
_JSON_PATH_ENVELOPE = Envelope(kind="json_path", path="response")


def _assert_process_dead(pid: int) -> None:
    """Cross-platform confirmation that `pid` no longer exists.

    POSIX: `os.kill` raises `ProcessLookupError` (ESRCH) for a dead pid.
    Windows has no ESRCH equivalent -- verified empirically on this runtime:
    a pid that was never valid raises `OSError` (WinError 87, "the parameter
    is incorrect"), while a pid that has since exited raises `PermissionError`
    (WinError 5, "access is denied"; still an `OSError` subclass) -- so any
    `OSError` there is the sign a live process would not have produced
    (killing a genuinely alive process on Windows raises nothing at all).
    """
    if sys.platform == "win32":
        with pytest.raises(OSError):
            os.kill(pid, signal.SIGTERM)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def test_successful_run_is_marked_succeeded():
    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())
    assert result.exit_code == 0
    assert result.result.succeeded is True
    assert result.orphans_suspected is False


def test_nonzero_exit_is_a_failure():
    result = spawn.run_process([sys.executable, FAKE, "crash"], None, 30, Path.cwd())
    assert result.exit_code == 1
    assert result.failure_reason


def test_exit_zero_with_offtopic_output_is_a_failure():
    """Verified against agy: exit 0 while answering an entirely different prompt."""
    result = spawn.run_process([sys.executable, FAKE, "offtopic"], None, 30, Path.cwd())
    assert result.exit_code == 0
    assert result.result.succeeded is False
    assert result.failure_reason


def test_empty_findings_without_marker_is_a_failure():
    result = spawn.run_process([sys.executable, FAKE, "empty"], None, 30, Path.cwd())
    assert result.result.succeeded is False


def test_no_findings_marker_is_a_success():
    result = spawn.run_process([sys.executable, FAKE, "no_findings"], None, 30, Path.cwd())
    assert result.result.succeeded is True


@pytest.mark.slow
def test_timeout_kills_the_whole_process_group(tmp_path):
    """Corrected from the brief, as added robustness: rather than parsing a
    child pid out of stdout captured after a SIGKILL, have the fake friend
    write its child's pid to a file passed via argv before it hangs, then
    assert on that file once the timeout has been handled. (The stdout-based
    approach was checked directly against this implementation and passed
    5/5 -- the pump threads here drain continuously rather than only after
    the kill, so it isn't actually at risk of the truncation this rewrite
    guards against in general. The pidfile is kept anyway: it asserts the
    property directly instead of through an incidental side channel.)
    run_process() only returns once the group sweep has completed, so no
    extra sleep is needed here to avoid a race against the kill.
    """
    pidfile = tmp_path / "child.pid"
    result = spawn.run_process([sys.executable, FAKE, "hang", str(pidfile)], None, 2, Path.cwd())
    assert result.timed_out is True
    child_pid = int(pidfile.read_text().strip())
    _assert_process_dead(child_pid)  # already reaped


@pytest.mark.slow
def test_timeout_takes_precedence_over_parsing():
    """A killed friend is a failure regardless of what it managed to print."""
    result = spawn.run_process([sys.executable, FAKE, "hang"], None, 2, Path.cwd())
    assert result.failure_reason == "timeout"


# --- Adversarial reaping probes (not in the brief) ---
#
# The brief's two verified hazards are (1) descendants must not survive a
# timeout and (2) exit status is not evidence of success. The task asked for
# an active attempt to defeat the reaping in (1) beyond the single hang/child
# case the required tests cover. Each probe below targets one specific way a
# real agent CLI's process tree could misbehave. Results (which are reaped,
# which escape) are recorded in task-8-report.md; the honest outcome for
# `test_setsid_escapee_is_not_reaped` is that it escapes -- process groups
# cannot reach a descendant that gives itself a new session, and this test
# exists to prove that limitation rather than hide it.


@pytest.mark.slow
def test_grandchild_is_reaped_through_two_levels(tmp_path):
    """child spawns its own child (a grandchild relative to the runner);
    neither calls setsid, so both stay in the friend's process group and
    killpg must reach both."""
    pidfile_child = tmp_path / "child.pid"
    pidfile_grandchild = tmp_path / "grandchild.pid"
    result = spawn.run_process(
        [sys.executable, FAKE, "grandchild", str(pidfile_child), str(pidfile_grandchild)],
        None,
        2,
        Path.cwd(),
    )
    assert result.timed_out is True
    child_pid = int(pidfile_child.read_text().strip())
    grandchild_pid = int(pidfile_grandchild.read_text().strip())
    _assert_process_dead(child_pid)
    _assert_process_dead(grandchild_pid)


@_POSIX_ONLY
@pytest.mark.slow
def test_sigterm_ignoring_friend_is_still_killed(tmp_path):
    """The friend itself ignores SIGTERM; SIGKILL cannot be ignored, so
    escalation must still finish it off within the grace windows."""
    pidfile = tmp_path / "self.pid"
    result = spawn.run_process(
        [sys.executable, FAKE, "ignore_sigterm", str(pidfile)],
        None,
        2,
        Path.cwd(),
    )
    assert result.timed_out is True
    pid = int(pidfile.read_text().strip())
    _assert_process_dead(pid)


@pytest.mark.slow
def test_closing_stdout_early_does_not_hang_the_runner():
    """A friend that closes stdout and then hangs must not cause the runner
    itself to block waiting for pipe EOF that will never come from that fd;
    the runner still has to notice the process never exits."""
    result = spawn.run_process(
        [sys.executable, FAKE, "close_stdout_then_hang"],
        None,
        2,
        Path.cwd(),
    )
    assert result.timed_out is True
    assert result.failure_reason == "timeout"


def test_exit0_with_leftover_descendant_is_reaped(tmp_path):
    """The friend prints a valid payload and exits 0 immediately, without
    waiting on a child it spawned. Nothing timed out, so hazard (1)'s
    timeout-triggered cleanup never fires on its own -- the runner must
    still sweep the process group after a clean exit, or the descendant
    (an MCP server, in the real-world case this hazard is modeled on) keeps
    running past the point the round was marked complete."""
    pidfile = tmp_path / "descendant.pid"
    result = spawn.run_process(
        [sys.executable, FAKE, "exit0_leaves_descendant", str(pidfile)],
        None,
        30,
        Path.cwd(),
    )
    assert result.timed_out is False
    assert result.exit_code == 0
    # fake_friend waits for this file before exiting (see _await_pidfile),
    # so a missing pidfile is a real regression in that handshake, not the
    # startup race this test used to lose under load ~40% of the time.
    assert pidfile.exists(), (
        "descendant never recorded its pid; fake_friend should not have exited "
        "until it did -- see _await_pidfile in tests/fake_friend.py"
    )
    descendant_pid = int(pidfile.read_text().strip())
    _assert_process_dead(descendant_pid)


@_POSIX_ONLY
@pytest.mark.slow
def test_setsid_escapee_is_not_reaped(tmp_path):
    """Honest negative result: a descendant that calls os.setsid() before
    the runner intervenes leaves the friend's process group entirely and
    forms its own session/group. killpg on the original group can never
    reach it. This is a real, accepted limitation of process-group-based
    reaping (the fix would require OS-level containment: cgroups, a Windows
    job object, or a pid namespace), not a bug in this runner. The test
    proves the limitation and then cleans the process up itself so it
    doesn't leak past the test suite."""
    pidfile = tmp_path / "escapee.pid"
    result = spawn.run_process(
        [sys.executable, FAKE, "escape", str(pidfile)],
        None,
        2,
        Path.cwd(),
    )
    assert result.timed_out is True
    assert result.orphans_suspected is True
    escapee_pid = int(pidfile.read_text().strip())
    # No ProcessLookupError here: the escapee is still alive. Demonstrate
    # that, then kill it directly (not via the runner) so the test suite
    # doesn't leave a stray sleeping process behind.
    os.kill(escapee_pid, 0)  # does not raise: still alive
    os.kill(escapee_pid, signal.SIGKILL)


def test_missing_binary_returns_a_spawn_result_not_an_exception():
    """run_process's signature says -> SpawnResult. The brief's Step 3 code
    only wrapped communicate() in try/except, so a missing binary raised
    FileNotFoundError straight out of Popen(). Task 12 calls this inside a
    thread pool, where an escaping exception would take down the whole
    dispatch instead of marking one friend failed."""
    missing = "/usr/bin/nope-does-not-exist-afriend"
    result = spawn.run_process([missing, "--anything"], None, 5, Path.cwd())
    assert result.exit_code is None
    assert result.timed_out is False
    assert result.orphans_suspected is False
    assert result.stdout == ""
    assert result.result.succeeded is False
    assert result.failure_reason == f"binary not found: {missing}"


@pytest.mark.posix_only(
    reason="Windows has no execute-bit permission concept -- executability "
    "there is gated by file extension/PE header, not a chmod-able mode, so "
    "there is no Windows equivalent of 'not executable but otherwise valid'",
)
def test_non_executable_binary_returns_a_spawn_result_not_an_exception(tmp_path):
    not_executable = tmp_path / "not-a-real-cli.sh"
    not_executable.write_text("#!/bin/sh\necho hi\n")
    not_executable.chmod(0o644)  # no execute bit
    result = spawn.run_process([str(not_executable)], None, 5, Path.cwd())
    assert result.exit_code is None
    assert result.timed_out is False
    assert result.orphans_suspected is False
    assert result.failure_reason == f"binary not executable: {not_executable}"


def test_enoexec_binary_returns_a_spawn_result_not_a_raw_traceback(tmp_path):
    """C3 (whole-branch review): run_process previously caught only
    FileNotFoundError and PermissionError from Popen(), which are the only
    two OSError subclasses is_executable-style checks anticipate. A broken
    shim -- executable bit set, but not a valid executable format at all
    (no shebang, not a real binary) -- raises OSError with errno ENOEXEC
    ("Exec format error"), a plain OSError that is neither of those two
    subclasses. Verified this reproduces on this machine (empty file,
    +x, Popen()) before writing this test; see spawn.run_process's own
    docstring for why E2BIG (Argument list too long, from an oversized
    prompt in a single argv element) is the other realistic OSError this
    same broad catch exists for, even though it isn't reliably triggerable
    in a portable test."""
    broken = tmp_path / "broken-shim"
    broken.write_bytes(b"")  # empty file: no shebang, no recognizable format
    broken.chmod(0o755)
    result = spawn.run_process([str(broken)], None, 5, Path.cwd())
    assert result.exit_code is None
    assert result.timed_out is False
    assert result.orphans_suspected is False
    assert result.result.succeeded is False
    assert result.failure_reason is not None
    assert "failed to start" in result.failure_reason
    assert str(broken) in result.failure_reason


@_POSIX_ONLY
@pytest.mark.slow
def test_setsid_escape_does_not_leak_pump_threads():
    """Finding: the earlier implementation's daemon pump threads blocked
    forever in a plain readline() on a pipe an escaped descendant held
    open, and never exited -- confirmed to reproduce on the first escape
    and compound linearly (5 invocations -> 10 leaked threads). The fix
    (non-blocking reads polled via selectors, gated by a stop_event set
    once the process-group sweep is done) is verified here directly: run
    the escape scenario repeatedly and assert the live thread count returns
    to its starting value instead of growing."""
    baseline = threading.active_count()
    escapee_pids = []
    # Five escapes already leaked ten threads before the fix, so more runs add
    # minutes, not evidence.
    for i in range(5):
        pidfile = Path(tempfile.mkdtemp()) / f"escapee-{i}.pid"
        result = spawn.run_process(
            [sys.executable, FAKE, "escape", str(pidfile)],
            None,
            2,
            Path.cwd(),
        )
        assert result.orphans_suspected is True
        escapee_pids.append(int(pidfile.read_text().strip()))

    # Give any thread that is (unexpectedly) still winding down a brief
    # window, then assert we're back at baseline -- not just "lower than
    # the worst case during the loop".
    deadline = time.monotonic() + 2.0
    while threading.active_count() > baseline and time.monotonic() < deadline:
        time.sleep(0.05)
    after = threading.active_count()

    for pid in escapee_pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)  # clean up the escapees directly

    assert after == baseline, (
        f"thread count did not return to baseline: before={baseline} after={after}"
    )


def test_nonzero_exit_with_otherwise_valid_output_is_still_a_failure():
    """Diagnosticity gap found while verifying the brief's own
    test_nonzero_exit_is_a_failure: "crash" mode prints nothing to stdout at
    all (only "boom" on stderr), so that test would still pass even if the
    exit-code check in run_process were deleted entirely -- normalize()
    would already report failure on empty/unparseable stdout for an
    unrelated reason, masking the exit-code branch having no effect.
    Confirmed by mutation: deleting the `if process.returncode != 0` branch
    left test_nonzero_exit_is_a_failure green. This test isolates the
    exit-code check specifically by pairing a nonzero exit with output that
    would otherwise parse as a full success."""
    result = spawn.run_process(
        [
            sys.executable,
            "-c",
            'import json,sys; print(json.dumps({"no_findings": True})); sys.exit(1)',
        ],
        None,
        30,
        Path.cwd(),
    )
    assert result.exit_code == 1
    assert result.result.succeeded is True  # normalize() alone would call this fine
    assert result.failure_reason == "exit 1"


# --- abort_event (Task 12 review, Finding 1) ----------------------------
#
# A run cancelled via Ctrl-C or a CI kill must not leave a metered agent CLI
# running unbounded. Without this parameter, run_process only ever exits
# early via the timeout deadline -- a caller with no way to signal "stop
# now" is stuck waiting out the full timeout_s regardless of what the user
# wants. abort_event gives a caller (cli.py's signal handler, here) that
# path, reusing the exact same process-group termination code a timeout
# already goes through.


def test_abort_event_terminates_promptly_instead_of_waiting_out_the_timeout():
    abort_event = threading.Event()
    threading.Timer(0.3, abort_event.set).start()
    started = time.monotonic()
    result = spawn.run_process(
        [sys.executable, FAKE, "hang"],
        None,
        30,
        Path.cwd(),
        abort_event=abort_event,
    )
    elapsed = time.monotonic() - started
    assert result.failure_reason == "aborted"
    assert result.timed_out is False  # distinct from a real timeout
    assert elapsed < 5, (
        f"took {elapsed:.1f}s -- should return within ~1s of the event, not near the 30s timeout"
    )


def _abort_once_pidfile_appears(
    pidfile: Path, event: threading.Event, timeout: float = 30.0
) -> None:
    """Signal `event` once the fake friend has recorded its child's pid.

    A fixed timer races the descendant. `fake_friend.py` must finish Python
    interpreter startup, spawn its own child, and write the pidfile, and
    under full-suite load that costs well over the 0.3s a fixed timer
    allowed. When the abort won that race the process group was reaped
    correctly, but the pidfile never appeared and the test failed with
    FileNotFoundError while reporting nothing about the reaping it exists to
    check -- the same race `fake_friend._await_pidfile` documents for the
    descendant-side modes, seen here from the caller's side.

    Waiting does not weaken the test: the descendant is alive and inside the
    process group at the moment the abort fires, which is the condition
    under test. The cap keeps a genuine failure to spawn from hanging the
    suite instead of failing it.
    """

    def _watch() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                if pidfile.read_text().strip():
                    break
            time.sleep(0.01)
        event.set()

    threading.Thread(target=_watch, daemon=True).start()


def test_abort_event_reaps_the_whole_process_group(tmp_path):
    pidfile = tmp_path / "child.pid"
    abort_event = threading.Event()
    _abort_once_pidfile_appears(pidfile, abort_event)
    result = spawn.run_process(
        [sys.executable, FAKE, "hang", str(pidfile)],
        None,
        30,
        Path.cwd(),
        abort_event=abort_event,
    )
    assert result.failure_reason == "aborted"
    child_pid = int(pidfile.read_text().strip())
    _assert_process_dead(child_pid)  # already reaped


def test_abort_event_none_is_unaffected_by_a_set_event_of_the_caller_s_own():
    """Sanity check on the default: a caller that never passes abort_event
    (every pre-existing caller/test) gets the exact prior behavior, timeout
    only -- the parameter defaulting to None must not somehow still poll
    some ambient/global event."""
    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())
    assert result.result.succeeded is True
    assert result.failure_reason is None


# --- Windows Job Object lifecycle (adversarial crossexam review) --------
#
# A crossexam review of the Windows port (codex/security, claude/ops, both
# independent) found the Job Object handle in run_process had no owner: it
# was acquired outside any try/finally, so an exception between creation and
# the normal termination block leaked it, and KILL_ON_JOB_CLOSE could never
# fire on a handle nothing ever closes. The tests below exercise the fix
# (job creation/termination now wrapped in try/finally) directly, along with
# the taskkill fallback's bounded timeout and false-positive fix, and the
# post-termination wait's own slow-rundown case.


@_WINDOWS_ONLY
def test_assign_failure_closes_the_leaked_job_handle(monkeypatch):
    """c-0002/c-0003: a failed wingroup.assign() used to leave the job handle
    `create_job()` returned neither closed nor terminated. spawn.py's except
    branch must close it immediately rather than leaking it to a `job = None`
    fallback that never sees that handle again."""
    from afriend import wingroup

    closed: list[int] = []
    real_close = wingroup.close

    def spy_close(handle: int) -> None:
        closed.append(handle)
        real_close(handle)

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    monkeypatch.setattr(wingroup, "assign", failing_assign)
    monkeypatch.setattr(wingroup, "close", spy_close)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert result.exit_code == 0
    assert result.result.succeeded is True
    # Exactly the one handle leaked by the failed assign(): job stays None
    # afterward, so the taskkill fallback below never calls wingroup.close
    # a second time.
    assert len(closed) == 1


@_WINDOWS_ONLY
def test_resume_failure_after_a_successful_assign_still_terminates_the_job(monkeypatch):
    """A second code review found `wingroup.resume()` was called from inside
    the job-setup try/finally, ahead of the pump-thread/wait-loop try/finally
    that is the only place the job ever gets terminated or closed. A resume()
    failure there escaped run_process before that cleanup ever ran, leaking
    the job handle (and leaving the suspended process a member of a job
    nothing would ever terminate) for the life of the whole afriend process.
    resume() must now be caught locally, with its own immediate cleanup."""
    from afriend import wingroup

    terminated: list[int] = []
    closed: list[int] = []
    real_terminate = wingroup.terminate
    real_close = wingroup.close

    def spy_terminate(job: int, *args: object, **kwargs: object) -> bool:
        terminated.append(job)
        return real_terminate(job, *args, **kwargs)  # type: ignore[arg-type]

    def spy_close(handle: int) -> None:
        closed.append(handle)
        real_close(handle)

    def failing_resume(_pid: int) -> None:
        raise OSError("simulated: could not resume the suspended process")

    monkeypatch.setattr(wingroup, "terminate", spy_terminate)
    monkeypatch.setattr(wingroup, "close", spy_close)
    monkeypatch.setattr(wingroup, "resume", failing_resume)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    # Reported as an ordinary early failure, not an escaping exception --
    # run_process's contract is "return a SpawnResult naming the cause."
    assert result.exit_code is None
    assert result.failure_reason is not None
    assert "resume" in result.failure_reason
    # The successfully-created, successfully-assigned job must still be
    # terminated and closed, not leaked.
    assert len(terminated) == 1
    assert len(closed) == 1
    # A real, still-suspended process is genuinely killable by
    # TerminateJobObject, so this cleanup actually succeeded.
    assert result.orphans_suspected is False


@_WINDOWS_ONLY
def test_resume_failure_reports_a_suspected_orphan_when_the_job_cleanup_fails(monkeypatch):
    """c-0002/c-0003 (second review): the resume-failure cleanup path called
    `wingroup.terminate()`/`taskkill_tree()` for effect only and
    `_early_failure` hardcoded `orphans_suspected=False` -- so a suspended
    process this cleanup could NOT actually kill was reported as a clean
    sweep, the one thing this signal exists to never do.

    The real `terminate()` still runs underneath (so the suspended test
    process is genuinely cleaned up and does not leak on this machine);
    only its reported outcome is overridden, to check the wiring rather
    than to actually leave anything behind."""
    from afriend import wingroup

    real_terminate = wingroup.terminate

    def failing_resume(_pid: int) -> None:
        raise OSError("simulated: could not resume the suspended process")

    def lying_terminate(job: int, *args: object, **kwargs: object) -> bool:
        real_terminate(job, *args, **kwargs)  # type: ignore[arg-type]
        return True

    monkeypatch.setattr(wingroup, "resume", failing_resume)
    monkeypatch.setattr(wingroup, "terminate", lying_terminate)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert result.failure_reason is not None
    assert "resume" in result.failure_reason
    assert result.orphans_suspected is True


@_WINDOWS_ONLY
def test_resume_failure_after_a_failed_assign_still_kills_the_suspended_process(monkeypatch):
    """The other half of the same fix: when Job Object setup itself had
    already failed (job is None) and resume() ALSO fails, the process was
    created CREATE_SUSPENDED and has no Job Object tracking it at all -- the
    only way to reach it is a direct taskkill, or it is orphaned, suspended,
    forever."""
    from afriend import wingroup

    killed: list[int] = []
    real_taskkill_tree = wingroup.taskkill_tree

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    def failing_resume(_pid: int) -> None:
        raise OSError("simulated: could not resume the suspended process")

    def spy_taskkill_tree(pid: int, **kwargs: object) -> bool:
        killed.append(pid)
        return real_taskkill_tree(pid, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(wingroup, "assign", failing_assign)
    monkeypatch.setattr(wingroup, "resume", failing_resume)
    monkeypatch.setattr(wingroup, "taskkill_tree", spy_taskkill_tree)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert result.exit_code is None
    assert result.failure_reason is not None
    assert "resume" in result.failure_reason
    assert len(killed) == 1
    # A real, still-suspended, jobless process is genuinely killable by
    # taskkill, so this cleanup actually succeeded.
    assert result.orphans_suspected is False


@_WINDOWS_ONLY
def test_resume_failure_after_a_failed_assign_reports_orphan_when_taskkill_fails(monkeypatch):
    """The job=None counterpart of the test above: `taskkill_tree`'s return
    value must reach `orphans_suspected` too, not just `wingroup.terminate`'s.
    The real `taskkill_tree` still runs underneath, so the suspended test
    process is genuinely cleaned up rather than leaked on this machine."""
    from afriend import wingroup

    real_taskkill_tree = wingroup.taskkill_tree

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    def failing_resume(_pid: int) -> None:
        raise OSError("simulated: could not resume the suspended process")

    def lying_taskkill_tree(pid: int, **kwargs: object) -> bool:
        real_taskkill_tree(pid, **kwargs)  # type: ignore[arg-type]
        return True

    monkeypatch.setattr(wingroup, "assign", failing_assign)
    monkeypatch.setattr(wingroup, "resume", failing_resume)
    monkeypatch.setattr(wingroup, "taskkill_tree", lying_taskkill_tree)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert result.failure_reason is not None
    assert "resume" in result.failure_reason
    assert result.orphans_suspected is True


@_WINDOWS_ONLY
def test_a_pump_thread_that_fails_to_start_still_reaches_job_cleanup(monkeypatch):
    """c-0003's broader claim: ANY exception raised between job setup and
    the normal termination block -- not just one from wingroup.assign()
    itself -- must still reach that termination block. Simulated here via a
    pump thread's start() raising (the exact failure scenario the finding
    named: RuntimeError: can't start new thread under concurrency)."""
    from afriend import wingroup

    real_start = threading.Thread.start
    terminated: list[int] = []
    real_terminate = wingroup.terminate

    def flaky_start(self: threading.Thread) -> None:
        if self.name == "stderr":
            raise RuntimeError("simulated: can't start new thread")
        real_start(self)

    def spy_terminate(job: int, *args: object, **kwargs: object) -> bool:
        terminated.append(job)
        return real_terminate(job, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(threading.Thread, "start", flaky_start)
    monkeypatch.setattr(wingroup, "terminate", spy_terminate)

    with pytest.raises(RuntimeError, match="can't start new thread"):
        spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert len(terminated) == 1


@pytest.mark.posix_only(
    reason="exercises the POSIX process-group cleanup path directly; "
    "the Windows equivalent is test_a_pump_thread_that_fails_to_start_still_reaches_job_cleanup"
)
def test_a_pump_thread_that_fails_to_start_still_reaps_the_process_group(monkeypatch):
    """The POSIX side of the same fix: the try/finally wrapping the pump
    threads and wait loop was generalized to both platforms, since an
    exception in that region already skipped `_terminate_group` here too,
    before this fix, for the identical reason."""
    real_start = threading.Thread.start
    reaped: list[int] = []
    real_terminate_group = spawn._terminate_group

    def flaky_start(self: threading.Thread) -> None:
        if self.name == "stderr":
            raise RuntimeError("simulated: can't start new thread")
        real_start(self)

    def spy_terminate_group(process: object, pgid: int) -> bool:
        reaped.append(pgid)
        return real_terminate_group(process, pgid)  # type: ignore[arg-type]

    monkeypatch.setattr(threading.Thread, "start", flaky_start)
    monkeypatch.setattr(spawn, "_terminate_group", spy_terminate_group)

    with pytest.raises(RuntimeError, match="can't start new thread"):
        spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert len(reaped) == 1


@_WINDOWS_ONLY
def test_taskkill_fallback_does_not_misreport_an_already_exited_friend_as_an_orphan(monkeypatch):
    """c-0005 (false positive half): taskkill exits 128 ("no process with
    that PID") for the ordinary case where the friend already exited before
    this fallback ran -- that used to be mapped to orphans_suspected=True on
    every clean run through this path, a blanket false alarm."""
    from afriend import wingroup

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    monkeypatch.setattr(wingroup, "assign", failing_assign)

    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    assert result.exit_code == 0
    assert result.result.succeeded is True
    assert result.orphans_suspected is False


@_WINDOWS_ONLY
def test_taskkill_fallback_is_bounded_and_reports_a_suspected_orphan_on_timeout(monkeypatch):
    """c-0005 (hang half): the taskkill fallback used to run with no
    timeout at all, so a hung taskkill (it depends on RPC/WMI paths that can
    themselves block on an unhealthy machine) could block a dispatch worker
    indefinitely. Only the taskkill invocation itself is intercepted here;
    everything else run_process shells out to during this call goes through
    the real subprocess.run unaffected.

    A code-review finding on an earlier version of this test: `selective_run`
    matched `argv[0] == "taskkill"` and never checked that a timeout was
    actually supplied, so it would still pass if a later change dropped
    `timeout=` from the real call -- it does not any more, since
    `wingroup.taskkill_tree` now resolves an absolute path (a CWD-hijack
    fix), which also means this mock must match by basename instead of the
    bare name it used to compare against."""
    from afriend import wingroup

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    real_run = subprocess.run

    def selective_run(argv: list[str], *args: object, **kwargs: object):
        if argv and Path(argv[0]).name.lower() == "taskkill.exe":
            assert kwargs.get("timeout") == spawn.KILL_GRACE_SECONDS, (
                "taskkill_tree must be called with a real bounded timeout"
            )
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])
        return real_run(argv, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(wingroup, "assign", failing_assign)
    monkeypatch.setattr(spawn.subprocess, "run", selective_run)

    started = time.monotonic()
    result = spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())
    elapsed = time.monotonic() - started

    assert result.orphans_suspected is True
    # Bounded by KILL_GRACE_SECONDS (5s) plus the normal-exit path's own
    # overhead, not left to hang on a taskkill that never returns.
    assert elapsed < 20


@_WINDOWS_ONLY
def test_a_friend_that_answered_is_stopped_cleanly_not_reported_as_exit_none():
    """Baseline for c-0007: a friend that has already written a complete
    json_path answer and then hangs must be recognized as deliberately
    stopped, not reported as a mystery failure -- the regression the
    WINDOWS_KILLED_AFTER_ANSWER_EXIT_CODE sentinel exists to prevent in the
    ordinary (fast-rundown) case."""
    result = spawn.run_process(
        [sys.executable, "-c", _ANSWER_THEN_HANG],
        None,
        30,
        Path.cwd(),
        envelope=_JSON_PATH_ENVELOPE,
    )

    assert result.stopped_after_answer is True
    assert result.failure_reason != "exit None"


@_WINDOWS_ONLY
def test_a_friend_that_answered_is_not_exit_none_when_rundown_outlives_the_wait(monkeypatch):
    """c-0007 itself: the process.wait() added to recognize a deliberately
    stopped friend suppressed its own TimeoutExpired without rechecking, so
    if THIS process's own rundown (closing handles, unloading DLLs) outlived
    KILL_GRACE_SECONDS, returncode stayed None and the friend's valid answer
    was reported as `failed: exit None` -- the exact regression the sentinel
    exists to prevent, reachable again through a slower path. Only the
    post-termination wait (called with timeout=KILL_GRACE_SECONDS) is
    intercepted; every other wait()/poll() call in this run goes through the
    real implementation unaffected."""
    real_wait = subprocess.Popen.wait

    def slow_rundown_wait(self: subprocess.Popen, timeout: float | None = None):
        if timeout == spawn.KILL_GRACE_SECONDS:
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)
        return real_wait(self, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", slow_rundown_wait)

    result = spawn.run_process(
        [sys.executable, "-c", _ANSWER_THEN_HANG],
        None,
        30,
        Path.cwd(),
        envelope=_JSON_PATH_ENVELOPE,
    )

    assert result.stopped_after_answer is True
    assert result.failure_reason != "exit None"
    assert result.orphans_suspected is True


@_WINDOWS_ONLY
def test_answered_then_killed_via_the_taskkill_fallback_is_not_reported_as_exit_1(monkeypatch):
    """A code review found that the `job=None` taskkill fallback could not
    tell "this friend answered and was then killed by us" apart from "this
    friend answered and then genuinely failed" -- taskkill does not let this
    process choose the exit code it produces (typically 1), so a friend
    that answered correctly and then hung was reported `failed: exit 1`
    with its already-normalized findings thrown away, exactly the failure
    scenario `killed_after_answering` exists to prevent. Forcing the
    job=None path (assign fails) reproduces it: without the fix, taskkill's
    exit 1 looks identical to a real on-purpose `sys.exit(1)`."""
    from afriend import wingroup

    def failing_assign(_job: int, _pid: int) -> None:
        raise OSError("simulated assignment failure")

    monkeypatch.setattr(wingroup, "assign", failing_assign)

    result = spawn.run_process(
        [sys.executable, "-c", _ANSWER_THEN_HANG],
        None,
        30,
        Path.cwd(),
        envelope=_JSON_PATH_ENVELOPE,
    )

    assert result.stopped_after_answer is True
    # The bug this guards against: taskkill's own exit code (1) being
    # mistaken for the friend's real exit status, discarding an
    # already-normalized answer as a false failure. `_ANSWER_THEN_HANG`'s
    # payload is not claim-shaped, so `failure_reason` is legitimately not
    # None here -- the point is specifically that it must not be "exit 1".
    assert result.failure_reason != "exit 1"


@_WINDOWS_ONLY
def test_a_non_oserror_in_the_resume_window_still_cleans_up_then_reraises(monkeypatch):
    """c-0007 (second review): the Popen-to-resume window only guarded
    against OSError, so anything else -- a MemoryError, a KeyboardInterrupt,
    a future refactor's bug -- escaped with the process created but never
    resumed: it runs no code, so it looks idle rather than runaway, and
    would sit suspended (holding a Job Object membership) until reboot.
    This is not an anticipated, nameable failure the way an OSError from
    resume() is, so it must still propagate -- but only after cleanup has
    run, not instead of it."""
    from afriend import wingroup

    terminated: list[int] = []
    real_terminate = wingroup.terminate

    def spy_terminate(job: int, *args: object, **kwargs: object) -> bool:
        terminated.append(job)
        return real_terminate(job, *args, **kwargs)  # type: ignore[arg-type]

    def resume_raises_something_else(_pid: int) -> None:
        raise MemoryError("simulated: unrelated failure inside the resume window")

    monkeypatch.setattr(wingroup, "terminate", spy_terminate)
    monkeypatch.setattr(wingroup, "resume", resume_raises_something_else)

    with pytest.raises(MemoryError):
        spawn.run_process([sys.executable, FAKE, "good"], None, 30, Path.cwd())

    # The job was still terminated before the exception propagated.
    assert len(terminated) == 1
