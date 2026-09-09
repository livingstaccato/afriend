"""Manage user-owned provider enablement and model defaults."""

import argparse
import json

from .. import providerconfig
from ..adapters import load_adapters
from ..errors import UsageError
from ..models import list_models, resolve_provider
from ..paths import ADAPTER_DIR


def _models(args: argparse.Namespace) -> int:
    """Ask providers what they offer. Never a list afriend made up."""
    registry = load_adapters(ADAPTER_DIR)
    names = [args.name] if getattr(args, "name", None) else sorted(registry)
    answers = [list_models(resolve_provider(registry, name)) for name in names]
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
            print(f"{answer.provider}\tno model listing: this CLI has no such command")
            continue
        if answer.error is not None:
            print(f"{answer.provider}\tunavailable: {answer.error}")
            continue
        for model in answer.models:
            print(f"{answer.provider}\t{model}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    known = set(load_adapters(ADAPTER_DIR))
    action = args.provider_command
    if action == "models":
        return _models(args)
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
