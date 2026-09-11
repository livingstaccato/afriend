"""Trust boundary for roster files and constructed argv.

A cloned repository is hostile input. Rather than blocklisting dangerous flag
spellings — which missed config overrides, inline settings JSON carrying
hooks, writable --add-dir, and profile layering — the roster is restricted to
values for a fixed set of keys. There is no mechanism for it to inject flags.

The value-level check that remains is direction-aware on purpose: refusing to
start because someone asked for a *safer* sandbox would be its own bug.
"""

from pathlib import Path
import re
import shlex
from typing import Any

from .errors import UsageError
from .ids import validate_friend_name

ROSTER_KEYS = frozenset({"name", "cli", "lens", "model", "effort", "scope", "timeout"})
VALID_SCOPES = frozenset({"repo", "doc"})

# Model ids seen in the wild: gpt-5.6-sol, claude-sonnet-4-6,
# cloudflare-ai-gateway/openai/gpt-5-nano, gemini-3.1-pro-high, qwen3:0.6b.
# The pattern admits all of those and nothing that begins with a dash, so a
# roster-supplied model string can never be mistaken for a flag.
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}")
# A lens name becomes a path component (`lenses/<lens>.md`) and part of the
# ledger identity (`adapters.friend_key`). The `--friend cli:lens` path is
# already held to this character set incidentally, because the friend name it
# builds from the lens runs through FRIEND_NAME_RE -- so a roster file that
# skipped the check accepted `../../..` where the flag could not, and the
# named file's body was spliced into the prompt sent to the provider. Same
# charset, so the two paths accept exactly the same lenses.
LENS_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# `lens="extracted"` is how the ledger marks a §14.2 extraction record, and
# resume._resumed_progress identifies already-applied extractions by exactly
# that string. A friend whose lens was literally `extracted` therefore had its
# ordinary critique claims counted as extraction progress, and the extraction
# halt became permanently unresumable -- every retry read the same ledger and
# refused. The sentinel has to be unavailable as an operator-chosen lens.
RESERVED_LENSES = frozenset({"extracted"})


def validate_lens(lens: str) -> str:
    """Validate one operator-supplied lens name, on any path it arrives by."""
    if not isinstance(lens, str):
        raise UsageError(f"invalid lens {lens!r}: expected a string, got {type(lens).__name__}")
    if lens in RESERVED_LENSES:
        raise UsageError(
            f"lens {lens!r} is reserved: the ledger uses it to mark extraction "
            "records, and a friend using it would make the run unresumable."
        )
    if LENS_RE.fullmatch(lens) is None:
        raise UsageError(
            f"invalid lens {lens!r}: must match {LENS_RE.pattern!r}. "
            "A lens names a file in the lens directory, not a path."
        )
    return lens


DENIED_FLAGS = frozenset(
    {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--approve-for-me",
        "--auto",
        "--yolo",
        "-y",
    }
)
DENIED_SANDBOX_VALUES = frozenset({"danger-full-access", "workspace-write"})
# --permission-mode is value-aware and direction-aware, same as --sandbox:
# bypassPermissions/dontAsk skip approval prompts entirely; plan/acceptEdits
# stay permitted (acceptEdits still requires read confirmation and never
# touches shell/bash tools without asking).
DENIED_PERMISSION_MODES = frozenset({"bypassPermissions", "dontAsk"})


def validate_roster_entry(entry: dict[str, Any]) -> dict[str, Any]:
    unknown = set(entry) - ROSTER_KEYS
    if unknown:
        raise UsageError(
            "roster entries may only set "
            f"{sorted(ROSTER_KEYS)}; found {sorted(unknown)}. "
            "Arbitrary flags are available only via --unsafe-extra-args on the "
            "command line, never from a file."
        )
    for required in ("name", "cli", "lens"):
        if not entry.get(required):
            raise UsageError(f"roster entry missing required key: {required}")
    # Types before patterns: `re.fullmatch` raises a bare TypeError on a
    # non-string, and cli.main catches only AfError -- so a one-character
    # typo in the operator's own roster file surfaced as a traceback instead
    # of the exit-2 usage error every other malformed value here gets.
    for keyed in ("name", "cli", "lens"):
        if not isinstance(entry[keyed], str):
            raise UsageError(
                f"invalid {keyed} {entry[keyed]!r}: expected a string, "
                f"got {type(entry[keyed]).__name__}"
            )
    validate_friend_name(entry["name"])
    validate_lens(entry["lens"])
    model = entry.get("model")
    if model is not None and not isinstance(model, str):
        raise UsageError(f"invalid model {model!r}: expected a string, got {type(model).__name__}")
    if model is not None and MODEL_RE.fullmatch(model) is None:
        raise UsageError(f"invalid model {model!r}: must match {MODEL_RE.pattern!r}")
    effort = entry.get("effort")
    if effort is not None and not isinstance(effort, str):
        raise UsageError(
            f"invalid effort {effort!r}: expected a string, got {type(effort).__name__}"
        )
    scope = entry.get("scope", "repo")
    if scope not in VALID_SCOPES:
        raise UsageError(f"invalid scope {scope!r}: expected one of {sorted(VALID_SCOPES)}")
    timeout = entry.get("timeout", 900)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise UsageError(f"invalid timeout {timeout!r}: expected a positive integer")
    return entry


def check_denied_values(argv: list[str], *, allow_outer_readonly: bool = False) -> None:
    """Reject argv values that weaken confinement.

    `allow_outer_readonly` is an adapter-only exception for Codex: its nested
    command sandbox cannot run inside afriend's read-only OS policy, so the
    adapter emits `danger-full-access` only while that outer policy binds the
    review workdir read-only. It is never used to inspect operator extra args.
    """
    for index, token in enumerate(argv):
        # A real CLI (e.g. codex, built on clap) accepts both `--flag value`
        # and `--flag=value`. Partitioning once up front and checking the
        # flag name against every denied set means the combined-token
        # spelling can never slip past a check written for the
        # space-separated form.
        flag, _, inline_value = token.partition("=")
        if flag in DENIED_FLAGS:
            raise UsageError(f"refusing to run: {flag} disables the sandbox this tool relies on")
        if flag in ("-s", "--sandbox"):
            value = inline_value or (argv[index + 1] if index + 1 < len(argv) else "")
            if value in DENIED_SANDBOX_VALUES and not (
                allow_outer_readonly and value == "danger-full-access"
            ):
                raise UsageError(f"refusing to run: sandbox mode {value!r} grants write access")
        if flag == "--permission-mode":
            value = inline_value or (argv[index + 1] if index + 1 < len(argv) else "")
            if value in DENIED_PERMISSION_MODES:
                raise UsageError(
                    f"refusing to run: permission mode {value!r} disables approval prompts"
                )


def strip_outer_readonly_argv(argv: list[str]) -> list[str]:
    """Drop the sandbox-weakening tokens an adapter emits for the outer policy.

    `--sandbox danger-full-access` is permitted by `check_denied_values` only
    while afriend's own read-only OS policy binds the review workdir. On a
    host with no mechanism that policy never materializes, and emitting the
    flag anyway actively disables the CLI's own inner sandbox with nothing
    outside it -- strictly worse than emitting no flag at all, and a breach
    of codex.toml's own stated invariant that the value "is refused when the
    outer mechanism is unavailable".

    Only the flag and its denied value are dropped. Suppressing the whole of
    `readonly_argv` would strip the harness rather than the weakening: agy's
    list also carries `--agent afriend-reviewer` and
    `--disable-slash-commands`, so dropping all of it would hand the friend a
    LARGER authority on precisely the run that already has no confinement,
    and it would no longer be the reviewer the report claims it was.

    Nothing here asserts what the CLI's own default sandbox does. Dispatch
    withdraws `readonly` from the capability for this case, so the run
    records the protection as lost rather than assuming a default holds.
    """
    kept: list[str] = []
    skip_value = False
    for index, token in enumerate(argv):
        if skip_value:
            skip_value = False
            continue
        flag, separator, inline_value = token.partition("=")
        if flag in ("-s", "--sandbox"):
            # Both spellings, for the same reason check_denied_values
            # partitions: a real CLI accepts `--flag value` and `--flag=value`
            # alike, and a strip written for one form leaves the other.
            if separator and inline_value in DENIED_SANDBOX_VALUES:
                continue
            if not separator and index + 1 < len(argv) and argv[index + 1] in DENIED_SANDBOX_VALUES:
                skip_value = True
                continue
        kept.append(token)
    return kept


def contain_path(base: Path, candidate: Path) -> Path:
    """Guarantee a constructed output path stays under the run directory."""
    base_resolved = Path(base).resolve()
    candidate_resolved = Path(candidate).resolve()
    if not candidate_resolved.is_relative_to(base_resolved):
        raise UsageError(f"path {candidate_resolved} escapes the run directory {base_resolved}")
    return candidate_resolved


def parse_unsafe_extra_args(raw: str | None, accepted: bool) -> list[str]:
    """§13's escape hatch: arbitrary flags, command line only.

    Two gates, both deliberate. It is refused without
    `--i-accept-unsandboxed`, because the flags this exists to pass are
    precisely the ones the allowlist rejects -- `codex -c`, `claude
    --settings` (hooks are arbitrary shell), `--add-dir` -- and reaching for
    it should require saying so. And it is refused if it carries a flag from
    DENIED_FLAGS, because those disable approval entirely; an escape hatch
    for "I need one more option" is not an escape hatch for "run with no
    guardrails at all".

    Split with shlex so quoting behaves the way a shell user expects rather
    than by whitespace, which would mangle any value containing a space.
    """
    if not raw:
        return []
    if not accepted:
        raise UsageError(
            "--unsafe-extra-args requires --i-accept-unsandboxed. It passes "
            "flags this tool cannot validate straight through to an agent "
            "CLI that is reviewing untrusted text; the acknowledgement is "
            "the point."
        )
    try:
        parsed = shlex.split(raw)
    except ValueError as exc:
        raise UsageError(
            f"--unsafe-extra-args is not parseable as a shell word list: {exc}"
        ) from exc
    for flag in parsed:
        if flag in DENIED_FLAGS:
            raise UsageError(
                f"refusing {flag!r} even under --unsafe-extra-args: it disables "
                "approval entirely. This flag exists to pass an option the "
                "allowlist has not learned yet, not to remove every guardrail."
            )
    return parsed
