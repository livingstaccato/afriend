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


def _native_npm_executable(found: str) -> str:
    """Bypass a recognized npm batch shim when it targets a native CLI.

    cmd.exe reparses npm's arguments and corrupts quoted inline JSON. These
    two packages expose native executables, so execute that same target
    directly. Do not replace custom launchers just because another install
    coexists beside them. Resolve the shim before looking up sibling files.
    """
    shim = Path(found).resolve()
    packages = {"claude": "@anthropic-ai/claude-code", "opencode": "@opencode/cli"}
    command = shim.stem.lower()
    if shim.suffix.lower() not in {".cmd", ".bat"} or command not in packages:
        return found
    relative = Path("node_modules") / packages[command] / "bin" / f"{command}.exe"
    try:
        with shim.open("rb") as stream:
            content = stream.read(16385).lower()
        if len(content) > 16384:
            return found
        target = str(relative).replace("/", "\\").lower().encode("ascii")
        native = shim.parent / relative
        # Match npm/cmd-shim's complete native forwarding template. A
        # substring also matches custom wrappers that set a profile or add
        # arguments; bypassing those would change the operator's selection.
        # Case/whitespace are insignificant in this fixed template. Normalize
        # slash style only in its forwarding path, not in command switches.
        lines = [b" ".join(line.split()) for line in content.splitlines() if line.strip()]
        if lines:
            lines[-1] = lines[-1].replace(b"/", b"\\")
        expected = [
            b"@echo off",
            b"goto start",
            b":find_dp0",
            b"set dp0=%~dp0",
            b"exit /b",
            b":start",
            b"setlocal",
            b"call :find_dp0",
            b'"%dp0%\\' + target + b'" %*',
        ]
        if native.is_file() and lines == expected:
            return str(native.resolve())
    except OSError:
        pass
    return found


def safe_which(name: str) -> str | None:
    """Like `shutil.which(name)`, but refuses a match that exists only
    because Windows implicitly searched the current directory ahead of
    `PATH`.

    Keeps `shutil.which`'s PATH/PATHEXT and executable-mode checks, rejecting a
    result whose containing directory is not one of the actual entries in
    `PATH`. A `PATH` that genuinely includes `.` (a user's own choice) still
    resolves normally: that directory is then a real entry, not merely the
    implicit injection this function exists to refuse. An authorized npm
    batch shim for a known native CLI is then resolved to its own executable
    target, avoiding cmd.exe's extra argument parse.
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
    return _native_npm_executable(found) if directory in path_entries else None


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
