"""`afriend providers models` reports what it asked, and asks in parallel."""

import argparse

from afriend.adapters import load_adapters
from afriend.commands import providers as providers_mod
from afriend.models import ProviderModels
from afriend.paths import ADAPTER_DIR


def _args(**kwargs):
    return argparse.Namespace(provider_command="models", json=False, name=None, **kwargs)


def test_the_registry_is_loaded_once_per_invocation(monkeypatch):
    loads: list[int] = []
    real = providers_mod.load_adapters
    monkeypatch.setattr(providers_mod, "load_adapters", lambda d: loads.append(1) or real(d))
    monkeypatch.setattr(
        providers_mod, "list_models", lambda a: ProviderModels(a.name, supported=False)
    )

    providers_mod.cmd_providers(_args())

    assert len(loads) == 1


def test_every_provider_is_asked_concurrently(monkeypatch, capsys):
    """Each listing is its own subprocess with its own timeout, so a serial
    sweep made the command's worst case their SUM -- one uninstalled provider
    could hold the first line of output for over two minutes."""
    import threading

    started = threading.Barrier(len(load_adapters(ADAPTER_DIR)), timeout=5)

    def blocking(adapter):
        started.wait()
        return ProviderModels(adapter.name, supported=True, models=("m",))

    monkeypatch.setattr(providers_mod, "list_models", blocking)

    # A serial implementation deadlocks the barrier and raises BrokenBarrier.
    assert providers_mod.cmd_providers(_args()) == 0
    assert "m" in capsys.readouterr().out


def test_an_adapter_without_a_listing_command_says_only_that(monkeypatch, capsys):
    """`ollama list` exists; the adapter simply does not declare it. Saying
    "this CLI has no such command" is the answer from memory that this whole
    command exists to replace."""
    monkeypatch.setattr(
        providers_mod, "list_models", lambda a: ProviderModels(a.name, supported=False)
    )

    providers_mod.cmd_providers(_args())
    out = capsys.readouterr().out

    assert "this adapter declares no listing command" in out
    assert "this CLI has no such command" not in out
