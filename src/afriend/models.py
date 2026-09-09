"""What models a provider says it offers.

Asked of the installed CLI, never inferred. A model list that afriend made up
would be worse than none: it would be quoted back at an operator choosing a
replacement for a provider that just ran out of quota, and a name the CLI
does not accept fails at dispatch rather than here.

A CLI that has no such command is reported as having none. codex is that
case today.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess

from .adapters import Adapter
from .errors import UsageError

# Long enough for a CLI that fetches its catalogue over the network (agy
# does), short enough that a hung provider does not hold up the answer.
MODELS_TIMEOUT_S = 30
MAX_MODELS = 500


@dataclass(frozen=True)
class ProviderModels:
    """What one provider answered, including "it cannot be asked"."""

    provider: str
    supported: bool
    models: tuple[str, ...] = ()
    error: str | None = None


def _parse(text: str, models_format: str) -> tuple[str, ...]:
    found: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if models_format == "tsv":
            # No tab means the CLI is talking to the operator, not listing.
            if "\t" not in line:
                continue
            candidate = line.split("\t", 1)[0].strip()
        else:
            candidate = line
        # A model id is one token. Anything with whitespace inside it is
        # prose that happened to reach this far.
        if not candidate or any(char.isspace() for char in candidate):
            continue
        if candidate not in found:
            found.append(candidate)
        if len(found) >= MAX_MODELS:
            break
    return tuple(found)


def list_models(adapter: Adapter, *, timeout_s: int = MODELS_TIMEOUT_S) -> ProviderModels:
    """Ask one provider for its models, or report why it cannot be asked."""
    if not adapter.models_argv:
        return ProviderModels(adapter.name, supported=False)
    argv = [adapter.binary, *adapter.models_argv]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return ProviderModels(adapter.name, supported=True, error="executable is not installed")
    except subprocess.TimeoutExpired:
        return ProviderModels(
            adapter.name, supported=True, error=f"listing timed out after {timeout_s}s"
        )
    except OSError as exc:
        return ProviderModels(adapter.name, supported=True, error=f"cannot run {argv[0]}: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit {completed.returncode}"
        return ProviderModels(adapter.name, supported=True, error=reason[:200])
    models = _parse(completed.stdout, adapter.models_format)
    if not models:
        return ProviderModels(
            adapter.name, supported=True, error="listing produced no recognizable model ids"
        )
    return ProviderModels(adapter.name, supported=True, models=models)


def resolve_provider(registry: dict[str, Adapter], name: str) -> Adapter:
    adapter = registry.get(name)
    if adapter is None:
        known = ", ".join(sorted(registry)) or "none"
        raise UsageError(f"unknown provider {name!r}; known providers: {known}")
    return adapter
