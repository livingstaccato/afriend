"""Manage user-owned provider enablement and model defaults."""

import argparse
import concurrent.futures
import json

from .. import providerconfig
from ..adapters import Adapter, load_adapters
from ..errors import UsageError
from ..models import list_models, resolve_provider
from ..paths import ADAPTER_DIR

# Every listing is its own subprocess with its own MODELS_TIMEOUT_S, so a
# serial sweep of the registry made the command's worst case the SUM of those
# timeouts -- five providers, any of them uninstalled or slow to fetch a
# catalogue, and nothing printed for over two minutes.
MODELS_CONCURRENCY = 5


def _models(args: argparse.Namespace, registry: dict[str, Adapter]) -> int:
    """Ask providers what they offer. Never a list afriend made up."""
    names = [args.name] if getattr(args, "name", None) else sorted(registry)
    adapters_to_ask = [resolve_provider(registry, name) for name in names]
    if len(adapters_to_ask) == 1:
        answers = [list_models(adapters_to_ask[0])]
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MODELS_CONCURRENCY, len(adapters_to_ask))
        ) as pool:
            answers = list(pool.map(list_models, adapters_to_ask))
    if args.json:
        print(
            json.dumps(
                {
                    "providers": {
                        answer.provider: {
                            "supported": answer.supported,
                            "models": list(answer.models),
                            "error": answer.error,
                        }
                        for answer in answers
                    }
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    for answer in answers:
        if not answer.supported:
            # What is actually known: this adapter declares no listing
            # command. Whether the CLI has one is a claim about the CLI that
            # nothing here checked -- `ollama list` exists, and printing "this
            # CLI has no such command" for it would be exactly the answer from
            # memory that this whole command exists to replace.
            print(f"{answer.provider}\tno model listing: this adapter declares no listing command")
            continue
        if answer.error is not None:
            print(f"{answer.provider}\tunavailable: {answer.error}")
            continue
        for model in answer.models:
            print(f"{answer.provider}\t{model}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    registry = load_adapters(ADAPTER_DIR)
    known = set(registry)
    action = args.provider_command
    if action == "models":
        return _models(args, registry)
    if action == "enable":
        providerconfig.set_enabled(args.name, True, known=known)
    elif action == "disable":
        providerconfig.set_enabled(args.name, False, known=known)
    elif action == "set-model":
        providerconfig.set_model(args.name, args.model, known=known)
    elif action == "clear-model":
        providerconfig.set_model(args.name, None, known=known)
    elif action != "list":
        raise UsageError(f"unknown providers action: {action!r}")

    if action != "list":
        return 0
    policy = providerconfig.load(known)
    payload = {
        "version": providerconfig.CONFIG_VERSION,
        "providers": {
            name: {"enabled": setting.enabled, "model": setting.model}
            for name, setting in sorted(policy.providers.items())
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for name, setting in sorted(policy.providers.items()):
            state = "enabled" if setting.enabled else "disabled"
            model = setting.model if setting.model is not None else "default"
            print(f"{name}\t{state}\tmodel: {model}")
    return 0
