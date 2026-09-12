"""Cross-platform exclusive advisory file locking.

POSIX locking here is `fcntl.flock`, which has no Windows equivalent -- the
Windows CRT's nearest analogue, `msvcrt.locking()`, locks a byte RANGE at the
current file position rather than the whole file. This module always locks
exactly one byte at offset 0 there: every caller in this codebase uses the
lock file purely as a mutex, never for its content, so which byte is
arbitrary as long as everyone agrees on it. Verified empirically (this
runtime): a zero-byte file locks and unlocks cleanly on Windows, on both a
read-write and a read-only handle, so no placeholder byte needs writing
first.

Every existing call site already handles the two outcomes `fcntl.flock`
produces: `BlockingIOError` for a non-blocking request that lost the race,
any other `OSError` for a real failure. `msvcrt.locking()` raises a plain
`PermissionError` for lock contention instead (verified empirically), so the
non-blocking path here re-raises it as `BlockingIOError` to match -- built so
callers written against the POSIX behavior need no changes at all beyond
importing this module instead of `fcntl` directly.

`fcntl.flock(LOCK_EX)` (no `LOCK_NB`) blocks indefinitely until the lock is
free. `msvcrt.locking(LK_LOCK)` only retries for about ten seconds before
giving up, which is a real semantic narrowing for the rare case of two
concurrent config-mutating commands -- so blocking mode here is a plain
poll loop over the non-blocking primitive instead of `LK_LOCK`, matching the
POSIX wait-forever behavior rather than the CRT's timeout.
"""

import os
import sys
import time

if sys.platform == "win32":
    import msvcrt

    _LOCK_NBYTES = 1
    _POLL_INTERVAL_S = 0.05

    def lock_exclusive(fd: int, *, blocking: bool = True) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_NBYTES)
                return
            except OSError as exc:
                if not blocking:
                    raise BlockingIOError(exc.errno, exc.strerror) from exc
                time.sleep(_POLL_INTERVAL_S)

    def unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, _LOCK_NBYTES)

else:
    import fcntl

    def lock_exclusive(fd: int, *, blocking: bool = True) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
