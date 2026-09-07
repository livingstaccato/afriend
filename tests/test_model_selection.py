"""The resolved roster records which layer selected every model."""

from dataclasses import replace
from pathlib import Path

import pytest

from afriend import adapters, readiness
from afriend.cliargs import build_parser
from afriend.commands import friends
from afriend.commands.runmeta import _validated_roster_entries
from afriend.errors import UsageError
from afriend.providerconfig import ProviderPolicy, ProviderSetting

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "afriend" / "assets" / "adapters"


def _artifact(tmp_path):
    artifact = tmp_path / "spec.md"
    artifact.write_text("# contract\n")
    return artifact


def _resolve(monkeypatch, tmp_path, *options, models=None, registry=None):
    registry = registry or adapters.load_adapters(ADAPTER_DIR)
    configured_models = models or {}
    monkeypatch.setattr(
        friends.providerconfig,
        "load",
        lambda *_args, **_kwargs: ProviderPolicy(
            {
                name: ProviderSetting(enabled=name == "codex", model=configured_models.get(name))
                for name in registry
            }
        ),
    )
    monkeypatch.setattr(
        readiness,
        "probe_deny_argv",
        lambda *_args: readiness.DenyProbeResult(True, "verified test shim"),
    )
    monkeypatch.setattr(
        friends.shutil, "which", lambda name: "/bin/codex" if name == "codex" else None
    )
    monkeypatch.setenv("AF_NO_HTTP_DISCOVERY", "1")
    args = build_parser().parse_args(["run", str(_artifact(tmp_path)), "--include-self", *options])
    return friends.resolve_friends(args, registry, None, [])


def test_global_model_is_recorded_as_the_invocation_source(monkeypatch, tmp_path):
    resolved = _resolve(monkeypatch, tmp_path, "--model", "invocation-model")

    assert resolved.specs[0].model == "invocation-model"
    assert resolved.specs[0].model_source == "invocation"


def test_global_model_outranks_explicit_friend_roster_and_provider_models(monkeypatch, tmp_path):
    roster = tmp_path / "roster.toml"
    roster.write_text(
        '[[friend]]\nname = "codex-ops"\ncli = "codex"\nlens = "ops"\nmodel = "roster-model"\n'
    )
    explicit = _resolve(
        monkeypatch,
        tmp_path,
        "--friend",
        "codex:ops:friend-model",
        "--model",
        "invocation-model",
        models={"codex": "configured-model"},
    )
    from_roster = _resolve(
        monkeypatch,
        tmp_path,
        "--roster",
        str(roster),
        "--model",
        "invocation-model",
        models={"codex": "configured-model"},
    )

    assert [(spec.model, spec.model_source) for spec in explicit.specs] == [
        ("invocation-model", "invocation")
    ]
    assert [(spec.model, spec.model_source) for spec in from_roster.specs] == [
        ("invocation-model", "invocation")
    ]


def test_explicit_friend_model_stays_distinct_from_a_roster_model(monkeypatch, tmp_path):
    explicit = _resolve(monkeypatch, tmp_path, "--friend", "codex:ops:friend-model")
    roster = tmp_path / "roster.toml"
    roster.write_text(
        '[[friend]]\nname = "codex-ops"\ncli = "codex"\nlens = "ops"\nmodel = "roster-model"\n'
    )
    from_roster = _resolve(monkeypatch, tmp_path, "--roster", str(roster))

    assert explicit.specs[0].model_source == "explicit-friend"
    assert from_roster.specs[0].model_source == "roster"


def test_provider_and_cli_defaults_have_distinct_sources(monkeypatch, tmp_path):
    configured = _resolve(monkeypatch, tmp_path, models={"codex": "configured-model"})
    defaulted = _resolve(monkeypatch, tmp_path)

    assert configured.specs[0].model == "configured-model"
    assert configured.specs[0].model_source == "provider-setting"
    assert defaulted.specs[0].model is None
    assert defaulted.specs[0].model_source == "cli-default"


def test_static_adapter_model_is_recorded_as_an_adapter_default(monkeypatch, tmp_path):
    registry = adapters.load_adapters(ADAPTER_DIR)
    registry["codex"] = replace(registry["codex"], default_model="static-model")

    resolved = _resolve(monkeypatch, tmp_path, registry=registry)

    assert resolved.specs[0].model == "static-model"
    assert resolved.specs[0].model_source == "adapter-default"


def test_provenance_survives_capacity_effort_and_host_marking(monkeypatch, tmp_path):
    resolved = _resolve(
        monkeypatch,
        tmp_path,
        "--friend",
        "codex:ops:friend-model",
        "--max-friends",
        "1",
        "--preset",
        "thorough",
        "--host-provider",
        "codex",
    )

    spec = resolved.specs[0]
    assert spec.model_source == "explicit-friend"
    assert spec.effort == "xhigh"
    assert spec.host_self_review is True
    assert spec.independent is False


def test_resume_provenance_is_validated_and_old_rosters_are_not_misattributed():
    row = {
        "name": "codex-ops",
        "cli": "codex",
        "lens": "ops",
        "model": "recorded-model",
        "effort": None,
        "scope": "doc",
        "timeout": 30,
        "model_source": "explicit-friend",
    }

    assert _validated_roster_entries([row])[0]["model_source"] == "explicit-friend"
    assert (
        _validated_roster_entries([{**row, "model": None}])[0]["model_source"] == "explicit-friend"
    )
    assert (
        _validated_roster_entries(
            [{key: value for key, value in row.items() if key != "model_source"}]
        )[0]["model_source"]
        == "recorded-unknown"
    )
    assert (
        _validated_roster_entries(
            [{key: value for key, value in {**row, "model": None}.items() if key != "model_source"}]
        )[0]["model_source"]
        == "cli-default"
    )
    with pytest.raises(UsageError, match="model_source"):
        _validated_roster_entries([{**row, "model_source": "invented"}])
