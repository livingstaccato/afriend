"""Resolve bare executable names the way `PATH` actually authorizes, not the
way Windows' loader does by default.

A code review of the Windows port found that `shutil.which()` -- and every
bare-name `subprocess` invocation (`git`, `taskkill`) that relies on
`CreateProcess`'s own search -- checks the *current directory* before `PATH`
on Windows (CPython's documented `NeedCurrentDirectoryForExePathW` behavior,
mirroring `CreateProcess`'s bare-name search order: the directory the calling
process loaded from, then its current directory, then `PATH`). A repository
under review is untrusted input (`trust.py` already says so for committed
Git hooks); a hostile checkout that ships `git.exe`, `codex.exe`, or
`claude.cmd` at its own root would otherwise have that file resolved and
executed as the operator, before any confinement decision is made -- on the
one platform with no OS sandbox at all.

POSIX's `execvp` never searches the current directory for a bare name, so
this exposure exists only because Windows is now a supported platform.
"""

import os
from pathlib import Path
import shutil
import sys


class _Unset:
    __slots__ = ()


_UNSET = _Unset()
_git_cache: str | _Unset | None = _UNSET


def safe_which(name: str) -> str | None:
    """Like `shutil.which(name)`, but refuses a match that exists only
    because Windows implicitly searched the current directory ahead of
    `PATH`.

    Keeps `shutil.which`'s own resolution -- PATHEXT handling, executable-
    mode checks, and everything else stay identical -- and only rejects a
    result whose containing directory is not one of the actual entries in
    `PATH`. A `PATH` that genuinely includes `.` (a user's own choice) still
    resolves normally: that directory is then a real entry, not merely the
    implicit injection this function exists to refuse.
    """
    found = shutil.which(name)
    if found is None or sys.platform != "win32":
        return found
    directory = os.path.normcase(str(Path(found).resolve().parent))
    path_entries = {
        os.path.normcase(str(Path(entry).resolve()))
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry
    }
    return found if directory in path_entries else None


def git_executable() -> str:
    """The absolute path to `git`, resolved once via `safe_which` and
    cached for the life of the process.

    Every caller that used to build `["git", *args]` should use
    `[git_executable(), *args]` instead: a bare `"git"` handed to
    `subprocess` is resolved by the OS's own bare-name search, which is
    exactly the CWD-precedence hazard this module exists to avoid. Raises
    `FileNotFoundError` if `git` cannot be safely resolved -- the same
    exception class `subprocess.Popen` itself raises for a missing
    executable, so a genuinely absent `git` fails exactly as it did before;
    only the CWD-hijack case changes, from silently running the planted
    binary to refusing it.
    """
    global _git_cache
    if isinstance(_git_cache, _Unset):
        _git_cache = safe_which("git")
    if _git_cache is None:
        raise FileNotFoundError("git not found on PATH")
    return _git_cache


def taskkill_executable() -> str:
    """The absolute path to `taskkill.exe`.

    Preferred over any PATH search: `%SystemRoot%\\System32\\taskkill.exe`
    is the canonical location (`SystemRoot` is already in
    `childenv.BASE_PASS`), and checking it directly avoids a bare-name
    search entirely rather than merely hardening one. Falls back to
    `safe_which` if `SystemRoot` is unset or the canonical path does not
    exist, then to the bare name as a last resort so a call site still gets
    a `FileNotFoundError` from `subprocess` (matching prior behavior)
    rather than a confusing failure from this module instead.
    """
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if system_root:
        canonical = Path(system_root) / "System32" / "taskkill.exe"
        if canonical.is_file():
            return str(canonical)
    return safe_which("taskkill") or "taskkill"
