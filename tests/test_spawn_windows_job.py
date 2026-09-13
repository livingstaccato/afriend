from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from afriend import spawn
from afriend.envelopes import Envelope

pytestmark = pytest.mark.process


FAKE = str(Path(__file__).resolve().parent / "fake_friend.py")

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
