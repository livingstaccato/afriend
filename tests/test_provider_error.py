"""A failed friend's audit row says what the CLI said, not what it printed.

codex on a spent quota writes its reason to stdout as a structured error
event and leaves only a banner on stderr. The audit row folded in the stderr
tail, so the row read `failed: exit 1 (stderr: Reading prompt from stdin...)`
and the one sentence that explained the failure -- and told you when the
quota resets -- was readable only by opening the raw capture.

The fixture is the real capture from run-20260909T092632-0226a90c.
"""

from pathlib import Path

from afriend.adapters import load_adapters
from afriend.envelopes import envelope_error, unwrap_envelope
from afriend.paths import ADAPTER_DIR

FIXTURES = Path(__file__).with_name("fixtures")

USAGE_LIMIT = (FIXTURES / "codex_usage_limit.ndjson").read_text(encoding="utf-8")


def _codex_envelope():
    envelope = load_adapters(ADAPTER_DIR)["codex"].envelope
    assert envelope is not None
    return envelope


def test_the_codex_quota_message_is_extracted_from_its_error_event():
    assert envelope_error(USAGE_LIMIT, _codex_envelope()) == (
        "You've hit your usage limit. Visit "
        "https://chatgpt.com/codex/settings/usage to purchase more credits "
        "or try again at Sep 14th, 2026 6:51 PM."
    )


def test_an_error_event_is_never_spliced_into_the_answer():
    """The reason error events are `error_rules` and not ordinary `rules`:
    matching one in `rules` would make the error text the friend's answer and
    leave it looking like it replied."""
    assert unwrap_envelope(USAGE_LIMIT, _codex_envelope()) is None


def test_an_adapter_that_declares_no_error_rules_extracts_nothing():
    envelope = load_adapters(ADAPTER_DIR)["opencode"].envelope
    assert envelope is not None
    assert envelope.error_rules == ()
    assert envelope_error(USAGE_LIMIT, envelope) is None


def test_the_last_error_event_wins():
    """Later events supersede earlier ones, the same rule the answer scan
    follows -- a stream that restates its failure has restated it, not
    reported two."""
    stream = (
        '{"type":"error","message":"first"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"error","message":"second"}\n'
    )
    assert envelope_error(stream, _codex_envelope()) == "second"


def test_a_malformed_line_does_not_poison_the_scan():
    stream = "not json\n" + USAGE_LIMIT
    assert envelope_error(stream, _codex_envelope()) is not None
