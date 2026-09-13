"""Tests for the cross-platform exclusive advisory lock (filelock.py)."""

import os
import threading
import time

import pytest

from afriend import filelock

pytestmark = pytest.mark.process


def test_lock_then_unlock_round_trips(tmp_path):
    path = tmp_path / "lock"
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT)
    try:
        filelock.lock_exclusive(fd)
        filelock.unlock(fd)
    finally:
        os.close(fd)


def test_non_blocking_lock_on_an_already_held_file_raises_blocking_io_error(tmp_path):
    path = tmp_path / "lock"
    held = os.open(str(path), os.O_RDWR | os.O_CREAT)
    contender = os.open(str(path), os.O_RDWR)
    try:
        filelock.lock_exclusive(held)
        with pytest.raises(BlockingIOError):
            filelock.lock_exclusive(contender, blocking=False)
    finally:
        filelock.unlock(held)
        os.close(held)
        os.close(contender)


@pytest.mark.slow
def test_blocking_lock_waits_for_the_holder_to_release(tmp_path):
    path = tmp_path / "lock"
    held = os.open(str(path), os.O_RDWR | os.O_CREAT)
    contender = os.open(str(path), os.O_RDWR)
    acquired = threading.Event()

    def _wait_then_acquire() -> None:
        filelock.lock_exclusive(contender)
        acquired.set()

    try:
        filelock.lock_exclusive(held)
        waiter = threading.Thread(target=_wait_then_acquire, daemon=True)
        waiter.start()
        time.sleep(0.3)
        assert not acquired.is_set(), "contender acquired the lock while the holder still held it"
        filelock.unlock(held)
        waiter.join(timeout=5)
        assert acquired.is_set(), "contender never acquired the lock after release"
        filelock.unlock(contender)
    finally:
        os.close(held)
        os.close(contender)


@pytest.mark.windows_only(
    reason="exercises msvcrt.locking()'s specific PermissionError-for-contention "
    "contract, which fcntl.flock on POSIX does not share"
)
def test_a_permanent_locking_failure_propagates_immediately_instead_of_looping(
    tmp_path, monkeypatch
):
    """A code review found `lock_exclusive` used to retry -- forever, in
    blocking mode -- on ANY OSError from msvcrt.locking(), not just lock
    contention. A permanent failure (an unsupported filesystem, a bad
    descriptor) became a silent, undiagnosable hang where `fcntl.flock`
    would have raised immediately. Only PermissionError (contention) may
    retry; anything else must propagate unchanged and promptly."""
    import msvcrt

    calls = {"n": 0}
    real_locking = msvcrt.locking

    def failing_locking(fd: int, mode: int, nbytes: int) -> None:
        calls["n"] += 1
        raise OSError(0, "simulated permanent locking failure")

    monkeypatch.setattr(msvcrt, "locking", failing_locking)
    path = tmp_path / "lock"
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT)
    try:
        with pytest.raises(OSError, match="simulated permanent locking failure"):
            filelock.lock_exclusive(fd)
        # Propagated on the first attempt -- not retried even once.
        assert calls["n"] == 1
    finally:
        monkeypatch.setattr(msvcrt, "locking", real_locking)
        os.close(fd)


@pytest.mark.windows_only(reason="exercises msvcrt.locking()'s Windows-only lock byte range")
def test_non_blocking_lock_still_converts_contention_to_blocking_io_error(tmp_path):
    """Regression guard alongside the fix above: a genuine contention
    failure (PermissionError) must still convert to BlockingIOError in
    non-blocking mode, exactly as documented -- the fix narrows which
    exception retries/converts, it must not stop converting the real case."""
    path = tmp_path / "lock"
    held = os.open(str(path), os.O_RDWR | os.O_CREAT)
    contender = os.open(str(path), os.O_RDWR)
    try:
        filelock.lock_exclusive(held)
        with pytest.raises(BlockingIOError):
            filelock.lock_exclusive(contender, blocking=False)
    finally:
        filelock.unlock(held)
        os.close(held)
        os.close(contender)
