"""Validation and normalization for resumable run checkpoints."""

import math
from typing import Any

from ..errors import UsageError
from ..outcomes import MAX_JSON_SAFE_INTEGER
from ..themes import ThemeProposal
from . import resumevalidation
from .checkpoint import (
    legacy_successful_friend_ids,
    normalize_friend_rows,
    normalize_repeat_tracker,
    normalize_resume_report_state,
)


def _checkpoint_count(meta: dict[str, Any], name: str, default: int) -> int:
    value = meta.get(name, default)
    if type(value) is not int or not 0 <= value <= MAX_JSON_SAFE_INTEGER:
        raise UsageError(f"cannot resume: saved {name} must be a nonnegative integer")
    return value


def _checkpoint_elapsed(meta: dict[str, Any]) -> float:
    value = meta.get("active_elapsed_s", 0.0)
    if type(value) not in {int, float}:
        raise UsageError(
            "cannot resume: saved active_elapsed_s must be a finite nonnegative number"
        )
    try:
        elapsed = float(value)
    except (OverflowError, ValueError) as exc:
        raise UsageError(
            "cannot resume: saved active_elapsed_s must be a finite nonnegative number"
        ) from exc
    if not math.isfinite(elapsed) or elapsed < 0:
        raise UsageError(
            "cannot resume: saved active_elapsed_s must be a finite nonnegative number"
        )
    return elapsed


def _checkpoint_successes(
    meta: dict[str, Any],
    friends: list[dict[str, Any]],
    critique_round: int,
    roster_roles: dict[str, tuple[bool, bool]],
) -> list[str]:
    if "successful_friend_ids" not in meta:
        successes = legacy_successful_friend_ids(friends, critique_round)
    else:
        value = meta["successful_friend_ids"]
        if type(value) is not list or not all(type(item) is str and item for item in value):
            raise UsageError(
                "cannot resume: saved successful_friend_ids must be a list of nonempty strings"
            )
        successes = list(value)
    if len(successes) != len(set(successes)):
        raise UsageError("cannot resume: saved successful_friend_ids must be unique")
    recorded_count = meta.get("succeeded_friends", len(successes))
    if type(recorded_count) is not int or recorded_count != len(successes):
        raise UsageError("cannot resume: saved succeeded_friends must match successful_friend_ids")
    if any(friend not in roster_roles for friend in successes):
        raise UsageError(
            "cannot resume: saved successful_friend_ids contains a friend outside the roster"
        )
    return [friend for friend in successes if roster_roles[friend][0]]


def _checkpoint_themes(meta: dict[str, Any]) -> tuple[list[ThemeProposal], bool]:
    resumevalidation.validate_metadata_bound(meta)
    raw_proposals = meta.get("theme_proposals", [])
    if type(raw_proposals) is not list:
        raise UsageError("cannot resume: saved theme_proposals must be a list")
    proposals: list[ThemeProposal] = []
    seen: set[ThemeProposal] = set()
    for index, raw in enumerate(raw_proposals):
        try:
            proposal = ThemeProposal.from_dict(raw)
        except UsageError as exc:
            raise UsageError(
                f"cannot resume: saved theme_proposals[{index}] is invalid: {exc}"
            ) from exc
        if proposal in seen:
            raise UsageError("cannot resume: saved theme_proposals contains a duplicate")
        seen.add(proposal)
        proposals.append(proposal)
    produced = meta.get("produced_new_themes", False)
    if type(produced) is not bool:
        raise UsageError("cannot resume: saved produced_new_themes must be a boolean")
    return proposals, produced


def _normalized_checkpoint(
    meta: dict[str, Any],
    *,
    roster_names: set[str],
    roster_roles: dict[str, tuple[bool, bool]],
    max_calls: int | None,
    max_rounds: object,
    require_friends: object,
) -> dict[str, Any]:
    normalized = dict(meta)
    spent_calls = _checkpoint_count(meta, "spent_calls", 0)
    attempted_calls = _checkpoint_count(meta, "attempted_calls", spent_calls)
    if attempted_calls != spent_calls:
        raise UsageError("cannot resume: saved attempted_calls must equal saved spent_calls")
    if max_calls is not None and spent_calls > max_calls:
        raise UsageError("cannot resume: saved spent_calls exceeds saved max_calls")
    iterations_run = _checkpoint_count(meta, "iterations_run", 0)
    rounds_run = _checkpoint_count(meta, "rounds_run", 0)
    dry_streak = _checkpoint_count(meta, "dry_streak", 0)
    resume_iteration = _checkpoint_count(
        meta, "resume_iteration", iterations_run if iterations_run > 0 else 1
    )
    if resume_iteration < 1:
        raise UsageError("cannot resume: saved resume_iteration must be a positive integer")
    if resume_iteration not in {max(1, iterations_run), iterations_run + 1}:
        raise UsageError(
            "cannot resume: saved resume_iteration is inconsistent with iterations_run"
        )
    friends = normalize_friend_rows(meta.get("friends", []), roster_names, roster_roles)
    if type(max_rounds) is not int or max_rounds < 1:
        raise UsageError("cannot resume: saved max_rounds must be a positive integer")
    critique_round = (resume_iteration - 1) * max_rounds + 1
    if any(row["round"] > critique_round for row in friends):
        raise UsageError("cannot resume: saved friends contain a row after the pending round")
    successes = _checkpoint_successes(meta, friends, critique_round, roster_roles)
    theme_proposals, produced_new_themes = _checkpoint_themes(meta)
    required = meta.get("required_friends", require_friends)
    if required is not None and (
        type(required) is not int or not 1 <= required <= MAX_JSON_SAFE_INTEGER
    ):
        raise UsageError("cannot resume: saved required_friends must be a positive integer or null")
    if required != require_friends:
        raise UsageError(
            "cannot resume: saved required_friends disagrees with the original invocation"
        )
    normalized.update(
        {
            "attempted_calls": attempted_calls,
            "spent_calls": spent_calls,
            "iterations_run": iterations_run,
            "rounds_run": rounds_run,
            "dry_streak": dry_streak,
            "resume_iteration": resume_iteration,
            "active_elapsed_s": _checkpoint_elapsed(meta),
            "successful_friend_ids": successes,
            "succeeded_friends": len(successes),
            "required_friends": required,
            "repeat_tracker": normalize_repeat_tracker(meta.get("repeat_tracker", {})),
            "friends": friends,
            "theme_proposals": [proposal.to_dict() for proposal in theme_proposals],
            "produced_new_themes": produced_new_themes,
        }
    )
    normalized.update(normalize_resume_report_state(meta))
    return normalized
