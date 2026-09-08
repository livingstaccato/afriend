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

import pytest

from afriend.readiness import HOST_ENV_MARKERS


@pytest.fixture(autouse=True)
def _isolate_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient host-detection markers so tests never inherit a host."""
    for marker in HOST_ENV_MARKERS:
        monkeypatch.delenv(marker, raising=False)
