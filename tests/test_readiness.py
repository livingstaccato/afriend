from pathlib import Path

import pytest

from afriend import adapters, workspaceassets
from afriend.adapters import Adapter
from afriend.authority import AuthorityPolicy
from afriend.errors import UsageError
from afriend.providerconfig import ProviderPolicy, ProviderSetting
from afriend.readiness import (
    DenyProbeResult,
    FriendReadiness,
    ReadinessState,
    assess_all,
    detect_host,
)
from afriend.workspaceassets import WorkspaceAsset

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "afriend" / "assets" / "adapters"


@pytest.fixture
def registry():
    return adapters.load_adapters(ADAPTER_DIR)


def test_current_codex_markers_detect_codex_host():
    assert detect_host({"CODEX_SESSION_ID": "s"}) == "codex"
    assert detect_host({"CODEX_THREAD_ID": "t"}) == "codex"


def test_explicit_host_provider_overrides_detected_markers():
    assert detect_host({"CLAUDECODE": "1"}, host_provider="opencode") == "opencode"


def test_ready_property_uses_the_ready_enum_member():
    row = FriendReadiness("codex", ReadinessState.READY, "available", "/bin/codex", None)
    assert row.ready is True
    assert FriendReadiness("codex", ReadinessState.UNAVAILABLE, "missing", "", None).ready is False


def test_disabled_http_provider_is_not_probed(registry):
    probes: list[str] = []
    rows = assess_all(
        registry,
        ProviderPolicy({"ollama": ProviderSetting(enabled=False)}),
        env={},
        which=lambda _: None,
        probe=lambda endpoint: probes.append(endpoint) or True,
    )
    assert rows["ollama"] == FriendReadiness(
        provider="ollama",
        state=ReadinessState.DISABLED,
        reason="disabled by provider policy",
        where=registry["ollama"].endpoint,
        model=None,
    )
    assert probes == []


def test_disabled_cli_provider_is_not_probed(registry):
    executable_probes: list[str] = []
    rows = assess_all(
        registry,
        ProviderPolicy({"codex": ProviderSetting(enabled=False)}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: executable_probes.append(name) or None,
        probe=lambda _: False,
    )
    assert rows["codex"].state is ReadinessState.DISABLED
    assert "codex" not in executable_probes


def test_a_friend_needing_an_absent_sandbox_is_ready_but_says_so(registry, monkeypatch):
    """doctor printed agy ready on hosts where every agy run is refused.

    Nothing in the readiness path was sandbox-aware, so upgrading 0.10.0 ->
    0.10.1 on a Linux box without bubblewrap left doctor green and exiting 0
    while dispatch refused agy on every run. The row stays READY -- the
    executable is there and --allow-unsandboxed-friend still runs it -- but
    it has to name the gap rather than assert an unqualified green.
    """
    monkeypatch.setattr("afriend.sandbox.detect", lambda *a, **k: None)

    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}",
        probe=lambda _: False,
        authority_policy=AuthorityPolicy(("*",)),
    )

    assert rows["agy"].state is ReadinessState.READY
    assert "no OS sandbox" in rows["agy"].reason
    # codex confines itself under the outer policy too, but claude does not
    # need one at all, so its row must stay unqualified.
    assert "no OS sandbox" not in rows["claude"].reason


def test_reachable_ollama_without_model_is_not_ready(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({"ollama": ProviderSetting(enabled=True)}),
        env={},
        which=lambda _: None,
        probe=lambda _: True,
    )
    assert rows["ollama"] == FriendReadiness(
        provider="ollama",
        state=ReadinessState.REACHABLE_UNCONFIGURED,
        reason="endpoint is reachable but no model is configured",
        where=registry["ollama"].endpoint,
        model=None,
    )
    assert rows["ollama"].ready is False


def test_configured_reachable_http_provider_is_ready(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({"ollama": ProviderSetting(model="qwen3:0.6b")}),
        env={},
        which=lambda _: None,
        probe=lambda _: True,
    )
    assert rows["ollama"] == FriendReadiness(
        provider="ollama",
        state=ReadinessState.READY,
        reason="endpoint is reachable",
        where=registry["ollama"].endpoint,
        model="qwen3:0.6b",
    )


def test_unavailable_http_provider_has_endpoint_and_configured_model(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({"ollama": ProviderSetting(model="qwen3:0.6b")}),
        env={},
        which=lambda _: None,
        probe=lambda _: False,
    )
    assert rows["ollama"] == FriendReadiness(
        provider="ollama",
        state=ReadinessState.UNAVAILABLE,
        reason="endpoint is unreachable",
        where=registry["ollama"].endpoint,
        model="qwen3:0.6b",
    )


def test_unavailable_cli_has_stable_empty_location(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda _: None,
        probe=lambda _: False,
    )
    assert rows["codex"] == FriendReadiness(
        provider="codex",
        state=ReadinessState.UNAVAILABLE,
        reason="executable 'codex' was not found",
        where="",
        model=None,
    )


def test_available_cli_is_ready_and_carries_model_preference(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({"codex": ProviderSetting(model="gpt-5.6-sol")}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda _: False,
    )
    assert rows["codex"] == FriendReadiness(
        provider="codex",
        state=ReadinessState.READY,
        reason="executable is available",
        where="/bin/codex",
        model="gpt-5.6-sol",
    )


def test_detected_host_is_classified_separately(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"CODEX_SESSION_ID": "session", "AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda _: False,
    )
    assert rows["codex"] == FriendReadiness(
        provider="codex",
        state=ReadinessState.HOST_EXCLUDED,
        reason="excluded because it is the detected host provider; reversible per"
        " run: --include-self adds it as advisory host review, and an explicit"
        " --friend NAME:LENS with --fresh-host-worker makes it an independent"
        " fresh worker",
        where="/bin/codex",
        model=None,
    )


def test_include_self_makes_detected_host_ready(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"CODEX_THREAD_ID": "thread", "AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda _: False,
        include_self=True,
    )
    assert rows["codex"].state is ReadinessState.READY


def test_explicit_selection_bypasses_disabled_host_and_http_discovery_only(registry):
    probes: list[str] = []
    rows = assess_all(
        registry,
        ProviderPolicy(
            {
                "codex": ProviderSetting(enabled=False),
                "ollama": ProviderSetting(enabled=False, model="qwen3:0.6b"),
            }
        ),
        env={"CODEX_SESSION_ID": "session", "AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda endpoint: probes.append(endpoint) or False,
        selection_policy=False,
    )

    assert rows["codex"].state is ReadinessState.READY
    assert rows["ollama"].state is ReadinessState.UNAVAILABLE
    assert probes == [registry["ollama"].endpoint]


def test_policy_blocked_provider_has_stable_reason_and_location(registry):
    def enforce(adapter):
        if adapter.name == "codex":
            raise UsageError("codex is blocked by test policy")

    rows = assess_all(
        registry,
        ProviderPolicy({"codex": ProviderSetting(model="gpt-5")}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda _: False,
        enforce=enforce,
    )
    assert rows["codex"] == FriendReadiness(
        provider="codex",
        state=ReadinessState.POLICY_BLOCKED,
        reason="codex is blocked by test policy",
        where="/bin/codex",
        model="gpt-5",
    )


def test_assessment_mapping_is_sorted_by_provider(registry):
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda _: None,
        probe=lambda _: False,
    )
    assert list(rows) == sorted(registry)


def test_scoped_grant_does_not_skip_other_providers_deny_capability_probes(registry):
    capability_checks: list[str] = []
    policy = AuthorityPolicy.from_grants(["agy"], registry)

    rows = assess_all(
        {name: registry[name] for name in ("agy", "codex")},
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}",
        include_self=True,
        authority_policy=policy,
        capability_probe=lambda adapter, _path: (
            capability_checks.append(adapter.name) or DenyProbeResult(True, "verified")
        ),
    )

    assert rows["agy"].state is ReadinessState.READY
    assert rows["codex"].state is ReadinessState.READY
    assert capability_checks == ["codex"]


def test_readiness_revalidates_asset_digest_before_executable_contact(monkeypatch, tmp_path):
    source_root = tmp_path / "package-assets"
    source_root.mkdir()
    (source_root / "payload").write_bytes(b"changed")
    adapter = Adapter(
        name="friend",
        binary="friend",
        base_argv=[],
        prompt_mode="stdin",
        prompt_flag="",
        readonly_argv=[],
        schema_flag="",
        model_flag="",
        internal_timeout_flag="",
        effort_kind="none",
        workspace_assets=(WorkspaceAsset("payload", ".friend/payload", "0" * 64),),
    )
    executable_probes = []
    monkeypatch.setattr(workspaceassets, "assets_root", lambda: source_root)

    rows = assess_all(
        {"friend": adapter},
        ProviderPolicy({}),
        env={},
        which=lambda name: executable_probes.append(name) or f"/bin/{name}",
    )

    assert rows["friend"].state is ReadinessState.POLICY_BLOCKED
    assert "digest mismatch" in rows["friend"].reason
    assert executable_probes == []


def test_confinement_is_decided_from_an_injected_seam_not_the_real_host(registry):
    """Readiness must be a function of its inputs on every machine.

    The probe called `sandbox.detect()` with no argument, so it consulted the
    real `shutil.which` while every other availability question went through
    the injected `which`. That made one row depend on whether the machine
    running the suite happens to have bubblewrap installed.
    """
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}",
        probe=lambda _: False,
        authority_policy=AuthorityPolicy(("*",)),
        detect_confinement=lambda: None,
    )

    assert rows["agy"].state is ReadinessState.READY
    assert "no OS sandbox" in rows["agy"].reason


def test_the_injected_which_is_not_used_as_the_confinement_oracle(registry):
    """`which` means "is this adapter's binary installed", nothing else.

    Answering the confinement question with it would report every mechanism
    absent whenever a test injects a `which` that names one adapter -- which
    is what every readiness test does -- so the qualification would appear on
    hosts that do have a sandbox.
    """
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}" if name == "codex" else None,
        probe=lambda _: False,
        detect_confinement=lambda: "bwrap",
    )

    assert rows["codex"].state is ReadinessState.READY
    assert rows["codex"].reason == "executable is available"


def _self_confining_but_opted_in() -> Adapter:
    """An adapter with a working read-only mode that opts into OS confinement.

    claude.toml's comment weighs exactly this combination, and the loader
    permits it: only `readonly_workdir` forces `self_confines` False.
    """
    return Adapter(
        name="both",
        binary="both",
        base_argv=[],
        prompt_mode="stdin",
        prompt_flag="",
        readonly_argv=["--read-only"],
        schema_flag="",
        model_flag="",
        internal_timeout_flag="",
        effort_kind="none",
        readonly=True,
        self_confines=True,
        sandbox_confine=True,
    )


def test_a_self_confining_friend_is_not_told_its_runs_will_be_refused():
    """The row predicted refusal with a predicate dispatch does not use.

    Dispatch refuses on `not is_self_confining`; the row asked
    `needs_os_confinement`, which is also true for a friend that opted into
    OS confinement while having a read-only mode of its own. Such a friend
    is not refused -- it falls back to its own flags and loses READ
    protection -- so the row must not tell the operator otherwise.
    """
    rows = assess_all(
        {"both": _self_confining_but_opted_in()},
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}",
        probe=lambda _: False,
        detect_confinement=lambda: None,
    )

    assert rows["both"].state is ReadinessState.READY
    assert "no OS sandbox" in rows["both"].reason
    assert "refused" not in rows["both"].reason


def test_a_friend_with_no_read_only_mode_is_still_told_runs_are_refused(registry):
    """The other leg of the same predicate must keep its warning."""
    rows = assess_all(
        registry,
        ProviderPolicy({}),
        env={"AF_NO_HTTP_DISCOVERY": "1"},
        which=lambda name: f"/bin/{name}",
        probe=lambda _: False,
        authority_policy=AuthorityPolicy(("*",)),
        detect_confinement=lambda: None,
    )

    assert "refused without --allow-unsandboxed-friend" in rows["agy"].reason
