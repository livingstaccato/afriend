"""Shared harness for the `afriend run` end-to-end test files.

Every subprocess launched via these helpers runs under a *constructed* PATH
containing only a symlink to the real `git` binary -- never the real,
inherited PATH. This machine may have codex/claude/agy/opencode installed
for interactive use; inheriting the real PATH would let friend discovery
find them and shell out to real, metered CLIs on every test run. `git` alone
is let through because isolation.py shells out to it for worktree
snapshots, and several tests exercise the repo-scope isolation path on
purpose.

AF_FAKE_FRIEND is the injection point that keeps `--friend fake:<mode>`
entirely off real CLIs: `cmd_run` treats cli == "fake" as a dedicated branch
that runs `$AF_FAKE_FRIEND <mode>` directly, bypassing adapter/build_argv
lookup, capability derivation, and roster resolution entirely (no adapter
named "fake" ever exists in the registry).
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest


def _make_af_shim() -> Path:
    """A tiny wrapper script that runs afriend's CLI via an absolute import,
    under the same interpreter these tests already use.

    This used to point straight at the installed console-script entry
    point next to `sys.executable`, on the theory that "setuptools
    generates console scripts as plain Python files, so passing one as a
    script argument to the interpreter runs it exactly as invoking it
    directly would." Verified false on Windows: pip/setuptools generate a
    native `.exe` launcher there instead (`afriend.exe`, not a bare
    `afriend` file), which `python.exe <path>` cannot run as a script at
    all -- every one of the ~40 call sites built on `AF` failed with
    "can't open file ...\\afriend: No such file or directory" before a
    single run directory was even created.
    `src/afriend/__main__.py` isn't a fix either: it uses `from .cli import
    main`, a relative import that requires launching via `-m afriend`, so
    it can't be run as a bare script path either. An absolute import
    sidesteps both: it works identically everywhere `import afriend`
    already does, which is guaranteed for these tests since they only run
    against an installed (or editable) `afriend`.
    """
    shim = Path(tempfile.mkdtemp(prefix="af-shim-")) / "afriend_shim.py"
    shim.write_text(
        "import sys\nfrom afriend.cli import main\nsys.exit(main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return shim


REPO = Path(__file__).resolve().parents[1]
AF = _make_af_shim()
FAKE = REPO / "tests" / "fake_friend.py"


def _safe_path_dir() -> Path:
    real_git = shutil.which("git")
    if real_git is None:
        pytest.skip("git not available on this machine")
    if sys.platform == "win32":
        # A link named `git` is not found through PATHEXT, and a link to Git for
        # Windows' launcher cannot find the installation it belongs to. Its own
        # directory is safe to use as long as no agent CLI lives there too.
        from afriend.adapters import load_adapters
        from afriend.paths import ADAPTER_DIR

        git_dir = Path(real_git).parent
        binaries = {adapter.binary for adapter in load_adapters(ADAPTER_DIR).values()}
        agents = sorted(b for b in binaries if b and shutil.which(b, path=str(git_dir)))
        if agents:
            pytest.skip(f"agent CLIs share git's directory: {agents}")
        return git_dir
    d = Path(tempfile.mkdtemp(prefix="af-safe-path-"))
    (d / "git").symlink_to(real_git)
    return d


def _env(extra=None):
    env = {
        "PATH": str(_safe_path_dir()),
        "XDG_CONFIG_HOME": tempfile.mkdtemp(prefix="af-safe-config-"),
        "AF_FAKE_FRIEND": f"{sys.executable} {FAKE}",
        # The safe PATH keeps real agent CLIs out of discovery, but an
        # HTTP friend is found by probing an endpoint, not by PATH -- so a
        # developer running ollama locally would otherwise be enlisted into
        # these runs and tests would pass or fail depending on whether
        # their server happened to be up.
        "AF_NO_HTTP_DISCOVERY": "1",
        # This dict is FIXED, and HOME below is the only thing forwarded from
        # the real environment -- so the autouse `_isolate_git_config`
        # fixture in conftest.py reaches none of the ~40 git invocations
        # driven from here. Without these two, every one of them would still
        # read the developer's `~/.gitconfig` through HOME, which is how
        # `commit.gpgsign` broke fixtures in the first place.
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    if sys.platform == "win32":
        # Without these, the subprocess under test can't even call
        # Path.home() -- Windows has no HOME by default, and `expanduser`
        # falls back through USERPROFILE / HOMEDRIVE+HOMEPATH, none of which
        # this fixed dict forwarded. Verified live: every one of these tests
        # failed before a run directory was even created, with
        # `RuntimeError: Could not determine home directory` out of
        # sessionconfig.config_path's `Path.home()` fallback. SystemRoot is
        # forwarded for the same reason childenv.py needs it for a
        # dispatched friend (see its own comment): Winsock can't resolve
        # DNS without it, which several of these tests' subprocesses also do
        # via git.
        for name in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "WINDIR", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
        # UTF-8 output, as this suite decodes it: the Windows default is the
        # ANSI code page, so a message with a "§" came back undecodable
        # and the reader thread left stderr as None.
        env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


def run_af(
    tmp_path,
    artifact,
    *extra,
    env_extra=None,
    mode="report",
    qualification_policy="distinct-sessions",
):
    """Dispatch a run for an end-to-end test.

    These tests exercise orchestration -- rounds, judging, ceilings, resume,
    isolation -- using two `fake:` friends, which are one provider family and
    so cannot satisfy the `cross-provider` default. They opt into the weakest
    policy explicitly rather than having `qualify()` special-case the `fake`
    transport: a policy that answers differently for test friends than for
    real ones is not the policy under test. Cases that *are* about evidence
    admission pass their own value (or None to exercise the real default).
    """
    policy = ["--qualification-policy", qualification_policy] if qualification_policy else []
    return subprocess.run(
        [
            sys.executable,
            str(AF),
            "run",
            str(artifact),
            "--mode",
            mode,
            "--out",
            str(tmp_path / "runs"),
            *policy,
            *extra,
        ],
        capture_output=True,
        text=True,
        env=_env(env_extra),
    )


def _git_commit(root: Path, message: str) -> None:
    # -c commit.gpgsign=false: this repo is disposable test scaffolding
    # under tmp_path, not the project's real history -- signing it would
    # only fail because _env() deliberately strips SSH_AUTH_SOCK/GPG_TTY
    # (see the safe-PATH rationale above), on any machine where
    # commit.gpgsign is enabled globally.
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
        env=_env(),
    )


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)

    def run(*a):
        return subprocess.run(a, cwd=root, check=True, capture_output=True, env=_env())

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "T")
    return root
