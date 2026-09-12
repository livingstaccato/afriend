"""An NDJSON rule can require a second condition (spec: codex.toml).

codex.toml's own comment describes the match precisely: "the item.completed
event whose item.type is 'agent_message', at item.text". The rule it
declared expressed only the first half, so it matched EVERY item.completed
event and rested on an unstated assumption -- that no other item kind
carries an `item.text` string. codex emits reasoning, command execution and
file-change items under that same `type`.

Found by cross-examining normalize.py, which noticed the declaration and its
own comment disagreeing.
"""

import json

import pytest

from afriend.adapters import load_adapters
from afriend.envelopes import Envelope, EnvelopeRule, parse_envelope, unwrap_envelope
from afriend.errors import UsageError
from afriend.paths import ADAPTER_DIR


def _event(item: dict) -> str:
    return json.dumps({"type": "item.completed", "item": item})


def test_a_rule_can_require_a_second_field_to_match():
    envelope = Envelope(
        kind="ndjson",
        rules=(
            EnvelopeRule(
                match_value="item.completed",
                field="item.text",
                where="item.type",
                equals="agent_message",
            ),
        ),
    )
    stream = "\n".join(
        [
            _event({"type": "reasoning", "text": "thinking out loud"}),
            _event({"type": "agent_message", "text": "the real answer"}),
        ]
    )
    assert unwrap_envelope(stream, envelope) == "the real answer"


def test_a_rule_without_the_second_condition_is_unchanged():
    """opencode's rules declare no `where`, and must keep matching on type
    alone."""
    envelope = Envelope(
        kind="ndjson",
        rules=(EnvelopeRule(match_value="item.completed", field="item.text"),),
    )
    assert unwrap_envelope(_event({"type": "anything", "text": "kept"}), envelope) == "kept"


def test_codex_declares_the_condition_its_own_comment_describes():
    registry = load_adapters(ADAPTER_DIR)
    envelope = registry["codex"].envelope
    assert envelope is not None
    rule = next(r for r in envelope.rules if r.field == "item.text")
    assert (rule.where, rule.equals) == ("item.type", "agent_message")


def test_codex_ignores_a_reasoning_item_that_carries_text():
    """End to end against the shipped adapter: a non-agent_message item with
    its own `text` must not be mistaken for the answer."""
    registry = load_adapters(ADAPTER_DIR)
    envelope = registry["codex"].envelope
    assert envelope is not None
    stream = _event({"type": "reasoning", "text": "internal deliberation"})
    assert unwrap_envelope(stream, envelope) is None


def test_parse_envelope_reads_the_condition_from_toml():
    envelope = parse_envelope(
        {
            "kind": "ndjson",
            "rules": [
                {
                    "type": "item.completed",
                    "field": "item.text",
                    "where": "item.type",
                    "equals": "agent_message",
                }
            ],
        }
    )
    assert envelope is not None
    assert envelope.rules[0].where == "item.type"
    assert envelope.rules[0].equals == "agent_message"


def test_a_non_string_equals_is_refused_rather_than_compared_as_empty():
    """The other half of the mis-declaration `_rule_where` already refuses.

    `equals` was coerced to "" whenever it was not a string, and
    `_scan_ndjson` then requires the `where` path to equal the empty string
    -- true for no real event. The rule never fires, the friend's answer is
    never recognised, and the run records that friend as having produced
    nothing, with no diagnostic anywhere. Matching everything silently and
    matching nothing silently are the same defect; only the direction
    differs.
    """
    for bad in (1, 1.5, True, None, ["a"], {"a": 1}):
        with pytest.raises(UsageError, match="`equals` must be a string"):
            parse_envelope(
                {
                    "kind": "ndjson",
                    "rules": [
                        {"type": "item", "field": "text", "where": "item.type", "equals": bad}
                    ],
                }
            )


def test_a_string_equals_with_a_where_is_still_accepted():
    envelope = parse_envelope(
        {
            "kind": "ndjson",
            "rules": [{"type": "item", "field": "text", "where": "item.type", "equals": "answer"}],
        }
    )
    assert envelope is not None
    assert envelope.rules[0].equals == "answer"
    assert envelope.rules[0].where == "item.type"


def test_a_rule_declaring_neither_key_is_unchanged():
    """`_rule_where`'s docstring promises this stays fine: a rule with no
    `where` and no `equals` matches on event type alone, deliberately."""
    envelope = parse_envelope({"kind": "ndjson", "rules": [{"type": "item", "field": "text"}]})
    assert envelope is not None
    assert envelope.rules[0].equals == ""
    assert envelope.rules[0].where == ""


def test_error_rules_get_the_same_refusal_as_answer_rules():
    """Both comprehensions had the identical coercion; a fix applied to one
    would leave the error path silently broken instead."""
    with pytest.raises(UsageError, match="`equals` must be a string"):
        parse_envelope(
            {
                "kind": "ndjson",
                "error_rules": [
                    {"type": "item", "field": "text", "where": "item.type", "equals": 7}
                ],
            }
        )
