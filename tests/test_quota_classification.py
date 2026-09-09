"""An exhausted allowance is not a broken credential.

Both make a friend fail, and telling them apart decides what happens next.
Auth is deterministic -- every remaining round fails the same way -- so it
aborts the run. A quota is deterministic for that provider and that
allowance only: the other friends have their own, and a different model on a
separate quota may still work. Aborting there would throw away reviews that
were going to succeed.

The message is the real one, from run-20260909T092632-0226a90c: codex failed
in five seconds during the 0.9.0 dogfood review with the quota text on
stdout and nothing but a banner on stderr.
"""

from afriend.adapters import load_adapters
from afriend.failures import AUTH, QUOTA, UNKNOWN, classify, quota_downgrade
from afriend.normalize import NormalizeResult
from afriend.paths import ADAPTER_DIR
from afriend.spawn import SpawnResult

QUOTA_TEXT = (
    "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
    "to purchase more credits or try again at Sep 14th, 2026 6:51 PM."
)


def _codex():
    return load_adapters(ADAPTER_DIR)["codex"]


def _outcome(*, provider_error=None, stderr="", failure_reason="exit 1", timed_out=False):
    return SpawnResult(
        argv=["codex"],
        exit_code=1,
        stdout="",
        stderr=stderr,
        duration_s=5.0,
        timed_out=timed_out,
        result=NormalizeResult(payload=None, errors=[], succeeded=False),
        failure_reason=failure_reason,
        orphans_suspected=False,
        provider_error=provider_error,
    )


def test_the_real_quota_message_classifies_as_quota():
    assert classify(_outcome(provider_error=QUOTA_TEXT), _codex()) == QUOTA


def test_a_quota_failure_is_not_an_auth_failure():
    """The distinction is the whole point: AUTH ends the run."""
    assert classify(_outcome(provider_error=QUOTA_TEXT), _codex()) != AUTH


def test_quota_wins_when_both_markers_match():
    """The ordering claim, isolated. Every other test here matches one marker
    or the other, so the order between them is unobserved -- and getting it
    wrong reads an exhausted allowance as a credential problem and aborts a
    run that had friends left to hear from.

    codex declares both: `usage limit` in its error message and `401
    Unauthorized` in stderr. A provider can emit both at once.
    """
    outcome = _outcome(provider_error=QUOTA_TEXT, stderr="401 Unauthorized")

    assert classify(outcome, _codex()) == QUOTA


def test_the_real_auth_message_still_classifies_as_auth():
    outcome = _outcome(stderr="401 Unauthorized")
    assert classify(outcome, _codex()) == AUTH


def test_an_unrecognized_failure_is_never_guessed_into_quota():
    assert classify(_outcome(provider_error="something else entirely"), _codex()) == UNKNOWN


def test_a_timeout_is_never_a_quota():
    """§14 gives timeout precedence: a killed friend's truncated output must
    not enter any interpretation path, and a provider that was cut off did
    not tell us it was out of allowance."""
    outcome = _outcome(provider_error=QUOTA_TEXT, timed_out=True)
    assert classify(outcome, _codex()) == UNKNOWN


def test_an_adapter_declaring_no_quota_markers_classifies_unknown():
    """agy has captured no quota failure, so it declares none and says so
    rather than matching on a plausible-looking word."""
    adapter = load_adapters(ADAPTER_DIR)["agy"]
    assert adapter.quota.declared() is False
    assert classify(_outcome(provider_error=QUOTA_TEXT), adapter) == UNKNOWN


def test_the_downgrade_names_the_friend_and_the_remediation():
    note = quota_downgrade("codex-ops-0", _codex(), [])

    assert "codex-ops-0" in note
    assert "reviewed nothing" in note
    assert "another provider" in note


def test_the_downgrade_offers_only_models_the_provider_listed():
    note = quota_downgrade("agy-ops-0", _codex(), ["model-a", "model-b"])

    assert "model-a, model-b" in note


def test_a_long_model_list_is_summarized_rather_than_dumped():
    note = quota_downgrade("agy-ops-0", _codex(), [f"m{i}" for i in range(12)])

    assert "and 7 more" in note
    assert "m11" not in note
