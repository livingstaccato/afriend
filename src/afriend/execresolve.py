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

import json
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


# Node-script CLIs whose npm `.cmd` shim is replaced by a direct `node`
# launch. Unlike claude/opencode these packages ship no native executable:
# the shim runs `node <package script> %*` through cmd.exe, and cmd.exe
# re-parses every argument. kimi has no stdin prompt path, so the untrusted
# artifact rides in argv -- a newline in it ends the command line early, and
# `&`, `|` or `%` in it are cmd.exe syntax. Measured on GitHub's Windows
# runner: the startup probe's `--prompt "...\n" --help` ran the prompt
# instead of printing help, because `--help` never arrived.
_NODE_SCRIPT_PACKAGES = {"kimi": "@moonshot-ai/kimi-code"}
# npm cmd-shim's complete Node-script template, case- and whitespace-
# normalized. Matched line for line, not by suffix: a wrapper that inserts
# Node options before the script (`--experimental-permission`, `--require`)
# would pass a suffix check, and launching node directly would then silently
# drop exactly the restrictions it added. Found by a kimi security review of
# this very launcher.
_NODE_SHIM_TEMPLATE = (
    b"@echo off",
    b"goto start",
    b":find_dp0",
    b"set dp0=%~dp0",
    b"exit /b",
    b":start",
    b"setlocal",
    b"call :find_dp0",
    b'if exist "%dp0%\\node.exe" (',
    b'set "_prog=%dp0%\\node.exe"',
    b") else (",
    b'set "_prog=node"',
    b"set pathext=%pathext:;.js;=;%",
    b")",
)
_NODE_SHIM_LAUNCH = b'endlocal & goto #_undefined_# 2>nul || title %comspec% & "%_prog%" '


def _node_npm_launch(found: str) -> list[str] | None:
    """`[node, script]` for a recognized npm shim of a known Node-script CLI.

    The script is taken from the package's own `package.json` `bin` entry,
    never parsed out of the batch file, and the shim must forward exactly
    that script with `%*` and nothing else, line for line -- a custom wrapper
    that adds arguments, node options or a profile keeps its own selection (and is then refused for
    an argv-prompt adapter by `build_argv`). Node is the shim's own sibling
    `node.exe` when present, which is what the shim itself would run,
    otherwise `node` from PATH through `safe_which`.
    """
    shim = Path(found).resolve()
    command = shim.stem.lower()
    package = _NODE_SCRIPT_PACKAGES.get(command)
    if shim.suffix.lower() not in {".cmd", ".bat"} or package is None:
        return None
    package_root = shim.parent / "node_modules" / package
    try:
        manifest = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
        bins = manifest.get("bin")
        relative = bins.get(command) if isinstance(bins, dict) else None
        if not isinstance(relative, str) or not relative:
            return None
        script = (package_root / relative).resolve()
        if package_root.resolve() not in script.parents or not script.is_file():
            return None
        with shim.open("rb") as stream:
            content = stream.read(16385).lower()
        if len(content) > 16384:
            return None
    except (OSError, ValueError):
        return None
    target = (Path("node_modules") / package / Path(relative)).as_posix()
    forward = b'"%dp0%\\' + target.replace("/", "\\").lower().encode("utf-8") + b'" %*'
    lines = [b" ".join(line.split()) for line in content.splitlines() if line.strip()]
    if lines != [*_NODE_SHIM_TEMPLATE, _NODE_SHIM_LAUNCH + forward]:
        return None
    sibling = shim.parent / "node.exe"
    node = str(sibling.resolve()) if sibling.is_file() else safe_which("node")
    if node is None:
        return None
    return [node, str(script)]


def launch_prefix(name: str) -> list[str] | None:
    """The argv prefix that runs `name`: usually `[safe_which(name)]`.

    On Windows a recognized npm shim of a Node-script CLI becomes
    `[node, script]`, so the arguments that follow reach the CLI through
    CreateProcess alone rather than a second cmd.exe parse.
    """
    found = safe_which(name)
    if found is None:
        return None
    if sys.platform == "win32":
        launch = _node_npm_launch(found)
        if launch is not None:
            return launch
    return [found]


def friend_launcher(name: str, binary: str, *, prompt_in_argv: bool) -> list[str] | None:
    """`launch_prefix(binary)`, refusing cmd.exe for an argv-prompt friend.

    The prompt is the untrusted artifact. Through a batch launcher a newline
    in it truncates the command line and `&`/`|`/`%` become cmd syntax, so a
    friend whose prompt rides in argv is refused rather than run that way.
    """
    launcher = launch_prefix(binary) if binary else None
    if (
        launcher is not None
        and prompt_in_argv
        and sys.platform == "win32"
        and Path(launcher[0]).suffix.lower() in {".cmd", ".bat"}
    ):
        from .errors import UsageError

        raise UsageError(
            f"{name} resolves to the batch launcher {launcher[0]}, and its prompt travels "
            "in argv; cmd.exe would re-parse the artifact under review. Install "
            f"{binary} from npm (afriend launches its Node script directly) or put a "
            "native executable first on PATH."
        )
    return launcher


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
