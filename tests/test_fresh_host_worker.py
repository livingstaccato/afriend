"""An explicitly requested fresh worker on the host's own provider family.

The invoking harness is always advisory: it may contribute findings but can
never satisfy a judging policy. A *separately launched* worker that happens to
use the same provider family is a different thing -- a real second execution,
which qualifies, while the report still discloses that it shares the host's
family.

Selecting one is the only way a Claude-hosted task can reach `cross-provider`
without configuring a third provider, so the path has to actually work.
"""

import pytest

from afriend import adapters, cli, readiness
from afriend.commands import friends as friends_module
from afriend.errors import UsageError
from afriend.paths import ADAPTER_DIR


@pytest.fixture(autouse=True)
def _verified_deny_probe(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "probe_deny_argv",
        lambda *_args: readiness.DenyProbeResult(True, "verified test shim"),
    )


@pytest.fixture(autouse=True)
def _every_cli_is_installed(monkeypatch):
    monkeypatch.setattr(friends_module.shutil, "which", lambda name: f"/usr/bin/{name}")


def _artifact(tmp_path):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# contract\n")
    return artifact


def _resolve(tmp_path, *extra):
    args = cli.build_parser().parse_args(
        ["run", str(_artifact(tmp_path)), "--out", str(tmp_path / "runs"), *extra]
    )
    return friends_module.resolve_friends(args, adapters.load_adapters(ADAPTER_DIR), None, [])


def test_fresh_host_worker_survives_the_host_family_filter(monkeypatch, tmp_path):
    """The marked spec must not be deleted by the advisory-host exclusion.

    `resolve_friends` marks matching specs and then applies the
    `spec.cli != host` filter that exists to drop the advisory host. Without
    an exemption the filter deletes the spec that was just marked, so the
    flag silently produces a one-friend roster on any non-Codex host.
    """
    monkeypatch.setenv("CLAUDECODE", "1")

    resolved = _resolve(
        tmp_path, "--friend", "codex:ops", "--friend", "claude:red", "--fresh-host-worker"
    )

    assert [spec.cli for spec in resolved.specs] == ["codex", "claude"]
    fresh = next(spec for spec in resolved.specs if spec.cli == "claude")
    assert fresh.fresh_host_worker is True
    assert fresh.independent is True
    assert fresh.host_self_review is False


def test_fresh_host_worker_qualifies_beside_another_provider(monkeypatch, tmp_path):
    """Design intent: fresh Claude worker + Codex satisfies cross-provider."""
    monkeypatch.setenv("CLAUDECODE", "1")

    resolved = _resolve(
        tmp_path, "--friend", "codex:ops", "--friend", "claude:red", "--fresh-host-worker"
    )
    families = {spec.cli for spec in resolved.specs if spec.independent}

    assert families == {"codex", "claude"}


def test_host_family_friend_without_the_flag_is_still_dropped(monkeypatch, tmp_path):
    """Existing behavior is unchanged when the flag is absent."""
    monkeypatch.setenv("CLAUDECODE", "1")

    resolved = _resolve(tmp_path, "--friend", "codex:ops", "--friend", "claude:red")

    assert [spec.cli for spec in resolved.specs] == ["codex"]


def test_fresh_host_worker_without_a_matching_friend_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDECODE", "1")

    with pytest.raises(UsageError, match="fresh-host-worker"):
        _resolve(tmp_path, "--friend", "codex:ops", "--fresh-host-worker")


def test_fresh_host_worker_outside_a_detected_host_is_refused(tmp_path):
    """No host detected and none declared: there is no host family to freshen."""
    with pytest.raises(UsageError, match="fresh-host-worker"):
        _resolve(tmp_path, "--friend", "codex:ops", "--fresh-host-worker")
