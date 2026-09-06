"""Inspect review-context preferences and compose explicit review evidence."""

import argparse
import json
from pathlib import Path

from .. import reviewcontext, sessionconfig
from ..errors import UsageError


def _policy_payload() -> dict[str, bool | str]:
    policy = sessionconfig.load().review_context
    return {
        "enabled": policy.enabled,
        "sources": policy.sources,
        "automatic_combine": policy.automatic_combine,
        "ambiguity": policy.ambiguity,
    }


def _one_source(values: list[str], option: str) -> Path | None:
    if len(values) > 1:
        raise UsageError(f"context compose accepts at most one {option} source")
    return Path(values[0]) if values else None


def _sidecar_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".json")


def cmd_context(args: argparse.Namespace) -> int:
    """Run one narrowly scoped context settings or composition action."""
    action = args.context_command
    if action == "show":
        payload = _policy_payload()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for name, value in payload.items():
                print(f"{name}: {value}")
        return 0
    if action == "set":
        sessionconfig.set_review_context(
            enabled=args.enabled,
            sources=args.sources,
            automatic_combine=args.automatic_combine,
            ambiguity=args.ambiguity,
        )
        print("updated review context")
        return 0
    if action == "compose":
        plan = _one_source(args.plan, "--plan")
        review = _one_source(args.review, "--review")
        output = Path(args.out).absolute()
        try:
            manifest = reviewcontext.compose(
                repo=Path(args.repo),
                out=output,
                plan=plan,
                review=review,
                worktree_diff=args.worktree_diff,
                ranges=args.ranges,
            )
        except OSError as exc:
            raise UsageError(f"cannot compose review context: {exc}") from exc
        receipt = {
            "intent": manifest.intent.value,
            "composite": str(output),
            "manifest": str(_sidecar_path(output)),
        }
        if args.json:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(
                f"review context {receipt['intent']}: composite {receipt['composite']}; "
                f"manifest {receipt['manifest']}"
            )
        return 0
    raise AssertionError(f"unhandled context action {action!r}")
