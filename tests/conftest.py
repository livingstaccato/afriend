"""Suite-wide isolation from the developer's own environment.

The test suite runs inside whatever harness the developer happens to be
using, and several of those harnesses advertise themselves through exactly
the variables afriend reads to detect its host. Running `make quality` from
inside Claude Code sets `CLAUDECODE=1`, which `detect_host` finds *before*
the `CODEX_SESSION_ID` a test set for itself -- `HOST_ENV_MARKERS` is ordered
and the first hit wins -- so five host-role tests failed locally while passing
in CI, where no marker is set.

Clearing every marker before each test makes host detection a property of the
test rather than of the machine. A test that wants a host still sets one with
`monkeypatch.setenv`, which runs after this fixture and therefore still wins.
"""

import os
import sys

from markers_support import apply_marks
import pytest

from afriend.readiness import HOST_ENV_MARKERS


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply the rule-based marks (markers_support.py) before `-m` deselects."""
    apply_marks(items, sys.platform)


@pytest.fixture(autouse=True)
def _isolate_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient host-detection markers so tests never inherit a host."""
    for marker in HOST_ENV_MARKERS:
        monkeypatch.delenv(marker, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Point every XDG location at a scratch dir, per test.

    The same concern as the two fixtures either side of this one, for the
    leak they did not cover. `rosterfile.discover()` reads
    `$XDG_CONFIG_HOME/afriend/roster.toml` (falling back to `~/.config`) and
    is documented as trusted and picked up automatically -- so a developer
    who has ever run `afriend init` has a roster the suite silently adopts.
    Eight tests across three files then fail with "roster does not satisfy
    qualification policy" and "no usable friends after readiness filtering",
    naming friends from a file that is nowhere in the repository.

    Found the hard way: a bare `afriend init` run while reproducing an
    unrelated finding created that file mid-session, and the suite went from
    green to eight failures with no code change between the two runs. A test
    result that depends on whose machine it runs on is not a test result,
    and the failure mode is the bad direction -- it can just as easily turn
    a real failure green.

    `tmp_path_factory` rather than `tmp_path` so this composes with tests
    that take neither, and the directory is created so a read of it does not
    itself fail differently from a read of a real empty config home.
    """
    root = tmp_path_factory.mktemp("xdg")
    for variable in (
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        target = root / variable.lower()
        target.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(target))


@pytest.fixture(autouse=True)
def _isolate_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the developer's own git configuration for every test.

    The same concern one level up from `commit.gpgsign false`, which nine
    fixtures set individually in two spellings while two other git-using
    modules set nothing. That per-site version only ever covered the setting
    someone had already been bitten by: the one new annotated-tag test
    inherited `tag.gpgsign` from the developer's config, and `git tag -a`
    exits 128 with "unable to sign the tag" for anyone who has it set.

    Pointing both config scopes at os.devnull covers commit.gpgsign,
    tag.gpgsign, gpg.format, core.hooksPath, commit.template and
    init.defaultBranch at once, and covers whatever the next inherited
    setting turns out to be. The per-fixture lines are left in place: they
    are harmless, and end-to-end tests build their own environment dict (see
    e2e_helpers._env) rather than inheriting this one.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
