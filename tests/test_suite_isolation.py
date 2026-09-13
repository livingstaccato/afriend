"""The suite must not read the developer's own afriend configuration.

`rosterfile.discover()` reads `$XDG_CONFIG_HOME/afriend/roster.toml`, falling
back to `~/.config`, and that file is documented as trusted and picked up
automatically. Nothing isolated it, so anyone who had ever run `afriend init`
ran a different test suite from everyone else.

This was found the hard way: a bare `afriend init`, run while reproducing an
unrelated finding, created that file mid-session, and the suite went from
green to eight failures across three files with no code change in between --
all of them naming friends (`claude-assumptions`, `codex-ops`) that appear
nowhere in this repository. The direction that actually matters is the other
one: the same leak can turn a real failure green.
"""

import os
from pathlib import Path

from afriend import rosterfile


def _under_tmp(path: Path) -> bool:
    return "pytest" in str(path) or str(path).startswith(("/tmp", "/private/var"))


def _outside_real_user_config(path: Path) -> bool:
    """Not simply "outside home": Windows keeps its temporary directory inside
    the user profile, so every scratch path there is under home."""
    home = Path.home()
    real = (home / ".config", home / ".local", home / ".cache")
    return not any(location == path or location in path.parents for location in real)


def test_every_xdg_location_is_redirected_away_from_the_developers_home():
    for variable in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        value = os.environ.get(variable)
        assert value, f"{variable} must be set, not merely unset"
        resolved = Path(value)
        assert _under_tmp(resolved), (variable, value)
        assert _outside_real_user_config(resolved), (variable, value)


def test_the_trusted_roster_path_cannot_reach_a_real_user_roster():
    """The specific read that caused the eight failures."""
    path = rosterfile.default_roster_path()
    assert _under_tmp(path), path
    assert _outside_real_user_config(path), path
    # And with nothing written there, discovery finds nothing -- which is
    # what every test that does not build its own roster assumes.
    assert rosterfile.discover() is None


def test_a_roster_written_during_a_test_does_not_escape_into_the_next_one(tmp_path):
    """Writing one where the code would look for it stays inside this
    test's own scratch directory."""
    path = rosterfile.default_roster_path()
    # Assert BEFORE writing, not after. With the fixture removed this test
    # created a roster.toml in the real ~/.config/afriend -- the very file
    # whose presence it exists to prevent. A guard that causes the damage it
    # checks for is worse than no guard.
    assert _under_tmp(path), path
    assert _outside_real_user_config(path), path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[[friend]]\nname = "x"\ncli = "codex"\nlens = "ops"\n', encoding="utf-8")
    assert rosterfile.discover() == path
