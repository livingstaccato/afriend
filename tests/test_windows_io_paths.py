"""Windows behaviour the POSIX suite can still hold the code to.

Each test fakes the one thing Windows does differently -- no selector on a
pipe, text-mode descriptors by default, PermissionError for opening a
directory, a generic OSError for a missing working directory -- and checks
the code no longer depends on the POSIX answer. The Windows CI job found
every one of these as a real failure.
"""

import errno
import os
from pathlib import Path
import subprocess
import sys

import pytest

from afriend import jsonio, reviewcontext, spawn
from afriend.commands import reviewcontext as rc
from afriend.errors import UsageError

_FAKE_O_BINARY = 0x4000_0000


def _no_selectors(monkeypatch):
    def refuse():
        raise OSError(10038, "An operation was attempted on something that is not a socket")

    monkeypatch.setattr("selectors.DefaultSelector", refuse)


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


@pytest.mark.git
def test_git_output_is_read_without_a_selector(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _no_selectors(monkeypatch)

    top = reviewcontext._git_bytes(repo, "rev-parse", "--show-toplevel").decode().strip()

    assert Path(top).resolve() == repo.resolve()


@pytest.mark.git
def test_git_output_over_the_limit_is_refused_without_a_selector(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _no_selectors(monkeypatch)

    with pytest.raises(UsageError, match="exceeds the 4-byte limit"):
        reviewcontext._git_bytes(repo, "rev-parse", "--show-toplevel", limit=4)


@pytest.mark.git
def test_git_stderr_still_names_the_failure_without_a_selector(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _no_selectors(monkeypatch)

    with pytest.raises(UsageError, match=r"git rev-parse --verify no-such-ref failed: \S"):
        reviewcontext._git_bytes(repo, "rev-parse", "--verify", "no-such-ref")


def _record_open_flags(monkeypatch) -> list[int]:
    """Give os a fake O_BINARY and record whether each open asked for it."""
    monkeypatch.setattr(os, "O_BINARY", _FAKE_O_BINARY, raising=False)
    real_open = os.open
    seen: list[int] = []

    def recording_open(path, flags, *args, **kwargs):
        seen.append(flags & _FAKE_O_BINARY)
        return real_open(path, flags & ~_FAKE_O_BINARY, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    return seen


def test_an_artifact_is_read_in_binary_mode(tmp_path, monkeypatch):
    artifact = tmp_path / "crlf.md"
    artifact.write_bytes(b"line one\r\nline two\r\n")
    seen = _record_open_flags(monkeypatch)

    payload, _text = rc.read_artifact_bytes_and_text(artifact)

    assert payload == b"line one\r\nline two\r\n"
    assert seen == [_FAKE_O_BINARY]


def test_bounded_json_is_read_in_binary_mode(tmp_path, monkeypatch):
    target = tmp_path / "sidecar.json"
    target.write_bytes(b'{"a": 1}\r\n')
    seen = _record_open_flags(monkeypatch)

    assert jsonio.read_bounded_bytes(target, label="sidecar") == b'{"a": 1}\r\n'
    assert seen == [_FAKE_O_BINARY]


def test_a_directory_artifact_is_refused_even_where_opening_it_is_denied(tmp_path, monkeypatch):
    real_open = os.open

    def windows_open(path, flags, *args, **kwargs):
        if Path(path).is_dir():
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", windows_open)

    with pytest.raises(UsageError, match="regular file"):
        rc.read_artifact_bytes_and_text(tmp_path)


def test_a_missing_working_directory_is_named_whatever_error_popen_raises(tmp_path, monkeypatch):
    def windows_popen(*_args, **_kwargs):
        raise NotADirectoryError(errno.ENOTDIR, "The directory name is invalid")

    monkeypatch.setattr(spawn.subprocess, "Popen", windows_popen)

    result = spawn.run_process([sys.executable, "-c", "pass"], None, 5, tmp_path / "missing")

    assert result.failure_reason is not None
    assert "working directory not found" in result.failure_reason
