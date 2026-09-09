"""The E2BIG warning for a prompt a CLI passes as one argv element.

Linux commonly caps a single argument near 128KB, and a composed review
context passes that easily -- issue #4, where claude failed to dispatch on
exactly this while codex handled the same artifact in the same run.

Every shipped adapter now reads its prompt from stdin, so this can no longer
be exercised end to end: claude moved for #4, opencode once it was verified
to read stdin, and agy once its stream-json transport was verified. The rule
still has to hold, because a user-authored TOML can declare either argv mode,
so it is tested here against synthetic adapters rather than deleted with the
last provider that needed it.
"""

from pathlib import Path

import pytest

from afriend.adapters import load_adapters
from afriend.dispatch import PROMPT_ARGV_WARN_BYTES, argv_size_warning
from afriend.paths import ADAPTER_DIR

OVERSIZED = "x" * (PROMPT_ARGV_WARN_BYTES + 1)


def _adapter(tmp_path: Path, name: str, mode: str, extra: str = "") -> object:
    (tmp_path / f"{name}.toml").write_text(
        f'name = "{name}"\nbinary = "{name}"\n'
        f'prompt_mode = "{mode}"\n'
        f'external_tools = "none"\n{extra}'
    )
    return load_adapters(tmp_path)[name]


@pytest.mark.parametrize(
    ("mode", "extra"),
    [("trailing-arg", ""), ("flag-value", 'prompt_flag = "--print"\n')],
)
def test_an_argv_adapter_is_warned_about_an_oversized_prompt(tmp_path, mode, extra):
    adapter = _adapter(tmp_path, "argv-cli", mode, extra)
    note = argv_size_warning("argv-cli-ops-0", adapter, OVERSIZED)

    assert note is not None
    assert "E2BIG" in note
    assert str(PROMPT_ARGV_WARN_BYTES + 1) in note
    assert mode in note


@pytest.mark.parametrize(
    ("mode", "extra"),
    [("trailing-arg", ""), ("flag-value", 'prompt_flag = "--print"\n')],
)
def test_a_prompt_at_the_threshold_is_not_warned_about(tmp_path, mode, extra):
    adapter = _adapter(tmp_path, "argv-cli", mode, extra)

    assert argv_size_warning("argv-cli-ops-0", adapter, "x" * PROMPT_ARGV_WARN_BYTES) is None


@pytest.mark.parametrize("name", ["agy", "claude", "codex", "opencode"])
def test_no_shipped_adapter_can_trip_the_warning(name):
    """Each of these reads its prompt from stdin, so the size of the prompt
    is not an argv question for any of them. This is the property the e2e
    version of this test used to demonstrate from the other side."""
    adapter = load_adapters(ADAPTER_DIR)[name]

    assert adapter.prompt_mode == "stdin"
    assert argv_size_warning(f"{name}-ops-0", adapter, OVERSIZED) is None


def test_a_fake_friend_is_never_warned_about(tmp_path):
    """The fake provider does not exec anything, so an argv cap cannot
    apply to it and a warning would be noise in every large-artifact test."""
    adapter = _adapter(tmp_path, "argv-cli", "trailing-arg")

    assert argv_size_warning("fake-ops-0", adapter, OVERSIZED) is None
