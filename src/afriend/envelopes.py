"""Where a friend's real answer lives inside its CLI's output wrapper.

Several CLIs wrap the model's answer in structured output of their own
(`claude --print --output-format json`, `codex exec --json`, `opencode run
--format json`, `agy --output-format json`). That wrapping is itself
well-formed JSON, so the inner answer usually sits inside a quoted string
value -- and `normalize._iter_balanced_objects` treats string content as
opaque, never descending into it. A friend's findings object is therefore
structurally unreachable by a plain brace-scan unless it is unwrapped first.

`Envelope` is a small declarative description of that shape, applied by
`normalize()` before it falls back to scanning the raw text. Split out of
normalize.py, which had grown past the then-current line cap.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

from .errors import UsageError

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

_JSON_ERRORS = (json.JSONDecodeError, ValueError, RecursionError)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _rule_where(rule: Mapping[str, object]) -> str:
    """The rule's `where` path, refusing a declaration that cannot be honoured.

    Coercing a missing or non-string `where` to "" silently DROPPED the
    second condition -- `_scan_ndjson` guards it with `if rule.where`, so
    `equals` was kept and never enforced, and the rule matched on the event
    type alone. That is exactly the over-matching `where`/`equals` was added
    to close: codex's answer rule then also caught reasoning,
    command-execution and file-change items, splicing them into the answer.
    A rule that declares neither key is still fine; one that declares
    `equals` without a usable `where` is a mis-declaration, and must say so
    rather than run as something else.
    """
    where = rule.get("where", "")
    if not isinstance(where, str):
        raise UsageError(f"envelope rule `where` must be a string, got {type(where).__name__}")
    if "equals" in rule and not where:
        raise UsageError(
            "envelope rule sets `equals` without `where`: the second condition "
            "would be silently ignored and the rule would match on the event "
            "type alone. Give it a `where` path, or drop `equals`."
        )
    return where


@dataclass(frozen=True)
class EnvelopeRule:
    """One NDJSON matching rule: when `match_field` on a parsed line equals
    `match_value`, extract `field` (a dotted path) as one segment of the
    unwrapped answer text.

    `where`/`equals` add an optional SECOND condition, a dotted path on the
    same line and the value it must hold. codex needed it: its answer is
    "the item.completed event whose item.type is agent_message", and a rule
    that could only express the first half matched every item.completed --
    reasoning, command execution and file changes included -- resting on an
    unstated assumption that no other item kind carries `item.text`. A rule
    that declares neither matches on `match_value` alone, as opencode's do.
    """

    match_value: str
    field: str
    where: str = ""
    equals: str = ""


@dataclass(frozen=True)
class Envelope:
    """Declarative description of where a friend's real answer lives inside
    a CLI's structured-output wrapper. Two kinds, matching the two shapes
    verified against real CLI output (see the module docstring):

    - "json_path": the whole stdout is a single JSON object; `path` is a
      dotted key path to the string field holding the answer (agy: the
      top-level `response` field).
    - "ndjson": stdout is one JSON object per line (an event stream); each
      line's `match_field` (default "type") is compared against every rule
      in `rules`, and every match's `field` is extracted (opencode: an
      `"error"` event's `error.data.message`).

    There is deliberately no third kind for "I'm not sure". An adapter whose
    real envelope shape has not been captured simply has no `envelope` at
    all; see normalize()'s `structured_output` parameter for how that case
    is made legible without guessing a shape.

    Four of the five shipped adapters declare one, captured from the real
    CLIs. ollama does not, and takes the no-envelope path on every run: it
    is the HTTP transport rather than a wrapping CLI, so there is no
    envelope to capture. That path is therefore live and exercised, not
    merely reserved for adapters nobody has run yet -- which is how this
    docstring described it while claiming all five.
    """

    kind: str
    path: str = ""
    match_field: str = "type"
    rules: tuple[EnvelopeRule, ...] = ()
    # json_path only: a dotted path to the CLI's own error message, for the
    # case where the envelope carries one INSTEAD of an answer (agy: a
    # top-level `error` string beside an empty `response`). Read only after
    # normalizing has failed, so it can never turn a working answer into a
    # failure; it makes the failure say what the CLI said.
    error_path: str = ""
    # ndjson's equivalent. An event stream states its failure in an event
    # rather than a field, and that event is not the answer, so it cannot be
    # an ordinary rule: matching it in `rules` would splice the error text
    # into the answer and leave the friend looking like it replied.
    #
    # Without this, a CLI that failed for a reason it stated plainly -- codex
    # answering "You've hit your usage limit" -- was recorded as
    # `failed: exit 1` with the stderr banner folded in, and the reason was
    # readable only by opening the raw capture.
    error_rules: tuple[EnvelopeRule, ...] = ()
    # ndjson only: the `match_field` value carried by the event that ends the
    # stream. It is what `answer_is_complete` needs to stop waiting on a CLI
    # that has finished but not exited -- the same hang json_path solves by
    # parsing a complete object, which an event stream cannot do because a
    # later line may still carry the answer.
    terminal_event: str = ""


def _rule_equals(rule: Mapping[str, object]) -> str:
    """The rule's `equals` value, refusing one that cannot be compared.

    `_rule_where` above refuses `equals` without `where`. This is the same
    mis-declaration from the other side: a non-string `equals` was coerced
    to "", and `_scan_ndjson` then requires the `where` path to equal the
    empty string -- true for no real event. The rule never fires, the
    friend's answer is never recognised, and the run records it as having
    produced nothing, with no diagnostic anywhere. Silently matching
    everything and silently matching nothing are the same defect.
    """
    if "equals" not in rule:
        return ""
    equals = rule["equals"]
    if not isinstance(equals, str):
        raise UsageError(
            f"envelope rule `equals` must be a string, got {type(equals).__name__}: "
            "a non-string value would be compared as the empty string, so the rule "
            "would match no event and the friend's answer would be dropped unreported."
        )
    return equals


def parse_envelope(data: dict[str, Any] | None) -> "Envelope | None":
    """Build an Envelope from the `[envelope]` table of an adapter TOML, or
    return None if no (valid) envelope was declared.

    Absent or unrecognised sections still degrade to "no envelope", which
    normalize() treats as a safe, working fallback. But this no longer
    "never raises", and the distinction matters: a section that declares an
    ndjson RULE it cannot honour is refused with a UsageError rather than
    quietly running as something else. `_rule_where` and `_rule_equals`
    below say which mis-declarations those are and what each would silently
    do instead -- over-match every event, or match none of them.

    Note the blast radius, because it is wider than this function:
    `adapters.load_adapters` calls this, and `run`, `doctor`, `providers`,
    `init` and `setup` all call that, so one adapter's typo now fails every
    command rather than disabling that one adapter. That is the deliberate
    trade -- a rule that cannot be honoured must not be used anywhere -- but
    it means `doctor`, the command for diagnosing a broken setup, is itself
    unavailable until the TOML is fixed. The refusal text has to be enough
    to fix it without running anything."""
    if not data:
        return None
    kind = data.get("kind")
    if kind == "json_path":
        path = data.get("path", "")
        if not path:
            return None
        error_path = data.get("error_path", "")
        return Envelope(
            kind="json_path",
            path=path,
            error_path=error_path if isinstance(error_path, str) else "",
        )
    if kind == "ndjson":
        rules = tuple(
            EnvelopeRule(
                match_value=rule["type"],
                field=rule["field"],
                where=_rule_where(rule),
                equals=_rule_equals(rule),
            )
            for rule in data.get("rules", [])
            if isinstance(rule, dict) and rule.get("type") and rule.get("field")
        )
        error_rules = tuple(
            EnvelopeRule(
                match_value=rule["type"],
                field=rule["field"],
                where=_rule_where(rule),
                equals=_rule_equals(rule),
            )
            for rule in data.get("error_rules", [])
            if isinstance(rule, dict) and rule.get("type") and rule.get("field")
        )
        terminal_event = data.get("terminal_event", "")
        return Envelope(
            kind="ndjson",
            match_field=data.get("match_field", "type"),
            rules=rules,
            error_rules=error_rules,
            terminal_event=terminal_event if isinstance(terminal_event, str) else "",
        )
    return None


def _dotted_get(obj: object, path: str) -> object:
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _unwrap_json_path(raw: str, envelope: Envelope) -> str | None:
    """The whole text must itself be exactly one JSON object (agy's stdout
    is not wrapped in prose or fencing -- it IS the envelope). Anything that
    fails to parse as a single top-level object, or whose target field is
    missing/empty, unwraps to nothing -- the caller falls back to scanning
    the raw text."""
    cleaned = strip_ansi(raw).strip()
    try:
        parsed = json.loads(cleaned)
    except _JSON_ERRORS:
        return None
    if not isinstance(parsed, dict):
        return None
    value = _dotted_get(parsed, envelope.path)
    if isinstance(value, dict) and value:
        # The target is the answer itself, not a string holding it. claude
        # under --json-schema puts the validated object in
        # `structured_output` and a serialized copy in `result`; pointing
        # the envelope at the object rather than the copy means the thing
        # the CLI validated is the thing we parse. Re-serialized so the rest
        # of normalize() sees the same text it would have unwrapped.
        return json.dumps(value)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _unwrap_ndjson(raw: str, envelope: Envelope) -> str | None:
    """Scan every line as its own JSON object (an NDJSON event stream);
    every line whose `match_field` matches a rule contributes that rule's
    extracted field to the unwrapped text, latest first. A line that
    fails to parse (blank, partial, non-JSON) is simply skipped -- one
    malformed event must not poison the rest of a real stream.

    Latest first because in an event stream the final matching event is
    the answer and the earlier ones are progress. codex under
    `--output-schema` emits "I'm inspecting the repository..." as an
    `agent_message` that is itself a schema-valid findings object, then
    the real answer; extract_json keeps the first candidate that ranks
    best, so stream order handed it the progress line and lost the answer
    -- a high-severity finding, in the run that found this. Captured in
    tests/fixtures/codex_progress_then_findings.ndjson."""
    extracted = list(_scan_ndjson(raw, envelope, envelope.rules))
    if not extracted:
        return None
    return "\n".join(reversed(extracted))


def _scan_ndjson(raw: str, envelope: Envelope, rules: tuple[EnvelopeRule, ...]) -> Iterator[str]:
    """Every nonempty value a rule set matches, in stream order.

    One reader for both scans. They were near-verbatim copies differing only
    in which rule tuple they walked and in how they reduced the matches, and
    keeping eighteen duplicated lines in step was manual: the answer scan and
    the error scan have to stay DISTINCT (an error read as an answer makes a
    failed friend look like it replied), which is exactly the kind of
    invariant that a silent divergence in the shared half would break.
    """
    for line in strip_ansi(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except _JSON_ERRORS:
            continue
        if not isinstance(parsed, dict):
            continue
        type_value = parsed.get(envelope.match_field)
        for rule in rules:
            if rule.match_value != type_value:
                continue
            if rule.where and _dotted_get(parsed, rule.where) != rule.equals:
                continue
            value = _dotted_get(parsed, rule.field)
            if isinstance(value, str):
                if value.strip():
                    yield value
            elif isinstance(value, dict) and value:
                yield json.dumps(value)
            elif isinstance(value, list) and value:
                # A rule may name structured data rather than a string. agy
                # carries its findings array beside the prose `response` in
                # the same `result` event, and a rule that could only take
                # strings could not reach it -- so a run whose response was
                # unrelated prose failed with "no findings" while the real
                # findings sat one key away.
                #
                # A bare array is not an answer any consumer recognises, so
                # it is re-keyed under the name the rule reached it by:
                # `result.findings` yields {"findings": [...]}, which is the
                # shape normalize is looking for. Everything downstream still
                # receives answer TEXT.
                yield json.dumps({rule.field.rsplit(".", 1)[-1]: value})


def _ndjson_error(raw: str, envelope: Envelope) -> str | None:
    """The last error a rule matched. Later events supersede earlier ones:
    a stream that restates its failure has restated it, not reported two."""
    if not envelope.error_rules:
        return None
    found: str | None = None
    for value in _scan_ndjson(raw, envelope, envelope.error_rules):
        found = value.strip()
    return found


def unwrap_envelope(raw: str, envelope: Envelope) -> str | None:
    """Return the friend's answer text as described by `envelope`, or None
    if the envelope's own path/rules found nothing to extract -- "found
    nothing" is the caller's signal to fall back to scanning `raw` directly
    (see normalize())."""
    if envelope.kind == "json_path":
        return _unwrap_json_path(raw, envelope)
    if envelope.kind == "ndjson":
        return _unwrap_ndjson(raw, envelope)
    return None


def envelope_error(raw: str, envelope: Envelope) -> str | None:
    """The CLI's own error message, when its envelope declares where one
    lives and `raw` carries a non-empty one.

    Read only after normalizing has failed, so it can never turn a working
    answer into a failure. For an ndjson stream the last matching error event
    wins, on the same reasoning as the answer scan: later events supersede
    earlier ones.
    """
    if envelope.kind == "ndjson":
        return _ndjson_error(raw, envelope)
    if envelope.kind != "json_path" or not envelope.error_path:
        return None
    try:
        parsed = json.loads(strip_ansi(raw).strip())
    except _JSON_ERRORS:
        return None
    if not isinstance(parsed, dict):
        return None
    value = _dotted_get(parsed, envelope.error_path)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def answer_is_complete(text: str, envelope: Envelope) -> bool:
    """Whether a `json_path` friend has already said everything it will say.

    Only for that envelope kind, and the restriction is the whole argument:
    its contract is that stdout IS one JSON object, so a parseable object
    means the answer is in hand. An NDJSON friend streams events and a later
    line carries the answer, so the same check there would truncate it.

    This exists because agy, on its error path, writes its JSON and then does
    not exit until its own `--print-timeout` elapses. Measured across three
    occurrences against eleven clean ones: every successful run exits about
    2.5 seconds after the work it reports, and every hang exits at 906
    seconds having reported 163, 372 and 482 -- between seven and twelve
    minutes of waiting for a process that had already answered.

    The cheap guard first: a complete object ends with `}`, so the parse is
    attempted only when the buffer looks finished rather than on every poll.
    """
    if envelope.kind == "ndjson":
        return _ndjson_stream_finished(text, envelope)
    if envelope.kind != "json_path":
        return False
    text = text.strip()
    if not text.endswith("}"):
        return False
    try:
        return isinstance(json.loads(text), dict)
    except (ValueError, RecursionError):
        return False


# How far back the terminal-event scan looks. Both bounds are about cost:
# `answer_is_complete` runs on nearly every poll for an NDJSON friend, so the
# work it does must not grow with the stream it is watching.
TERMINAL_SCAN_LINES = 16
# A ceiling, not the window. The window is the last TERMINAL_SCAN_LINES lines,
# located by scanning back from the end -- so the work still does not grow
# with the stream, but a terminal event LONGER than a fixed byte count is no
# longer cut in half. At a flat 64 KiB it was: agy's `result` line carries the
# whole JSON-escaped findings payload, so a big answer (hence a long,
# expensive run) never matched, and the run paid the full --print-timeout this
# check exists to avoid. This bound now only caps the pathological case of a
# single enormous line.
TERMINAL_SCAN_BYTES = 8 * 1024 * 1024


def _terminal_window_start(text: str) -> int:
    """Index of the start of the last TERMINAL_SCAN_LINES lines of `text`.

    Found by walking newlines backwards, so the cost is the length of those
    few lines rather than of the whole buffer -- the flat-cost property this
    check needs, without a fixed byte window that truncates a long terminal
    event mid-line.
    """
    floor = max(0, len(text) - TERMINAL_SCAN_BYTES)
    cut = len(text)
    for _ in range(TERMINAL_SCAN_LINES):
        # Skip the trailing newline of the line we just consumed.
        nl = text.rfind("\n", floor, cut - 1 if cut > floor else floor)
        if nl == -1:
            return floor
        cut = nl + 1
    return cut


def _ndjson_stream_finished(text: str, envelope: Envelope) -> bool:
    """Whether the stream's declared terminal event has arrived.

    Scanned over a bounded window at the end of the buffer, and over several
    trailing lines rather than the last one alone. Both halves were wrong in
    the first version, in opposite directions:

    Reading only the final line meant anything agy emitted after its
    terminal `result` -- a trailing progress event, a plain-text banner on
    the way out -- hid that event for the rest of the wait, and the run paid
    the whole `--print-timeout` this check exists to avoid. agy writes
    `result` and then does NOT exit, so emitting something afterwards is its
    normal behaviour, not an edge case.

    Reading the whole buffer to fix that would have cost more the longer a
    friend ran, and this check fires on nearly every poll for NDJSON: each
    line ends with `}`, so the cheap `_buffer_looks_finished` guard in the
    caller almost never rejects it. Hence the window rather than a full
    scan. Past that window a `result` under hundreds of later events is not
    a stream that ended; it is a stream still running.
    """
    if not envelope.terminal_event:
        return False
    window = strip_ansi(text[_terminal_window_start(text) :])
    for line in reversed(window.splitlines()[-TERMINAL_SCAN_LINES:]):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except _JSON_ERRORS:
            # A half-written trailing line mid-stream, or the CLI's own
            # prose. Neither is the terminal event, and neither hides one.
            continue
        if isinstance(parsed, dict) and parsed.get(envelope.match_field) == envelope.terminal_event:
            return True
    return False
