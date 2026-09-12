"""The suite's own marks: registered, used, and applied where rules say.

`e2e` is applied from the file name and `posix_only` / `windows_only` become
skips centrally (markers_support.py), so these check the rules themselves
rather than trusting every file to have remembered them.
"""

from pathlib import Path
import re
import subprocess
import sys
import tomllib

from markers_support import is_e2e, platform_skip_reason
import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _registered() -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lines = config["tool"]["pytest"]["ini_options"]["markers"]
    return {re.split(r"[:(]", line, maxsplit=1)[0].strip() for line in lines}


def test_e2e_follows_the_file_name():
    assert is_e2e(Path("tests/test_run_end_to_end_gate.py"))
    assert is_e2e(Path("tests/test_resume_overbudget_e2e.py"))
    assert not is_e2e(Path("tests/test_spawn.py"))
    assert not is_e2e(Path("tests/e2e_helpers.py"))


def test_selecting_e2e_keeps_only_end_to_end_files():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-o",
            "addopts=--strict-markers",
            "-q",
            "--color=no",
            "-p",
            "no:cacheprovider",
            "-m",
            "e2e",
            "tests/test_run_end_to_end_authority.py",
            "tests/test_errors.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    collected = [line for line in completed.stdout.splitlines() if "::" in line]
    assert collected, completed.stdout + completed.stderr
    assert all(line.startswith("tests/test_run_end_to_end_authority.py::") for line in collected)


@pytest.mark.parametrize(
    ("name", "platform", "skipped"),
    [
        ("posix_only", "win32", True),
        ("posix_only", "linux", False),
        ("posix_only", "darwin", False),
        ("windows_only", "win32", False),
        ("windows_only", "linux", True),
        ("windows_only", "darwin", True),
    ],
)
def test_a_platform_mark_skips_only_off_its_platform(name, platform, skipped):
    reason = platform_skip_reason(name, "why", platform)
    assert (reason == "why") is skipped
    assert reason is None or skipped


def test_a_platform_mark_needs_a_reason_on_every_platform():
    for platform in ("win32", "linux"):
        with pytest.raises(pytest.UsageError, match="reason"):
            platform_skip_reason("posix_only", None, platform)


def test_windows_skips_are_marks_not_skipif():
    pattern = re.compile(r"skipif\(\s*sys\.platform\s*[!=]=\s*\"win32\"")
    offenders = [
        path.name
        for path in sorted(TESTS.glob("test_*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "use @pytest.mark.posix_only/windows_only(reason=...)"


def test_every_registered_mark_is_used():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in sorted(TESTS.glob("*.py")))
    unused = sorted(name for name in _registered() if f"mark.{name}" not in sources)
    assert unused == []


def test_make_test_fast_leaves_out_slow_tests_and_quality_does_not():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
    assert re.search(r"^\.PHONY:.*\btest-fast\b", makefile, re.MULTILINE)
    recipe = re.search(r"^test-fast:.*\n\t(.+)$", makefile, re.MULTILINE)
    assert recipe is not None
    assert '-m "not slow"' in recipe.group(1)
    quality = re.search(r"^quality:(.*)$", makefile, re.MULTILINE)
    assert quality is not None
    assert " test " in f"{quality.group(1)} "
    assert "test-fast" not in quality.group(1)
