"""Marks applied by rule rather than written on every test.

`e2e` follows the file name, so a new end-to-end file is marked without anyone
remembering to. `posix_only` / `windows_only` carry their reason and become a
skip on the other platform here, in one place, instead of a `skipif` per test.
"""

from collections.abc import Iterable
from pathlib import Path

import pytest

E2E_PREFIX = "test_run_end_to_end_"
E2E_SUFFIX = "_e2e.py"
PLATFORM_MARKS = ("posix_only", "windows_only")


def is_e2e(path: Path) -> bool:
    return path.name.startswith(E2E_PREFIX) or path.name.endswith(E2E_SUFFIX)


def platform_skip_reason(name: str, reason: str | None, platform: str) -> str | None:
    """The reason to skip a test marked `name` on `platform`, or None to run it."""
    if not reason:
        raise pytest.UsageError(f"@pytest.mark.{name} needs reason=...")
    windows = platform == "win32"
    skipped = windows if name == "posix_only" else not windows
    return reason if skipped else None


def apply_marks(items: Iterable[pytest.Item], platform: str) -> None:
    for item in items:
        if is_e2e(item.path):
            item.add_marker(pytest.mark.e2e)
        for name in PLATFORM_MARKS:
            mark = item.get_closest_marker(name)
            if mark is None:
                continue
            reason = platform_skip_reason(name, mark.kwargs.get("reason"), platform)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
