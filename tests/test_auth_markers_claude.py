"""claude's auth marker, checked against its real captured failure (§14).

Captured 2026-08-28. claude keeps credentials in the macOS Keychain, so there
is no file to remove or copy: the failure was provoked by running it under
this runner's own sandbox with no `~/Library/Keychains` grant, which denies
READ access for one child process. Nothing was logged out and nothing was
written.

That is also why claude is the one adapter this project declines to confine
in normal use -- granting the Keychain would hand a friend every credential
the operator has, which is worse than the gap it closes.
"""

import json
import sys

import pytest

from afriend import failures, spawn
from afriend.adapters import load_adapters
from afriend.normalize import normalize
from afriend.paths import ADAPTER_DIR
from afriend.spawn import SpawnResult

# Verbatim shape from the capture, trimmed to the fields that matter.
CAPTURED = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": None,
        "result": "Not logged in · Please run /login",
    }
)
# Same envelope, a DIFFERENT API failure. Everything auth-shaped about the
# object above is still true here.
RATE_LIMITED = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": 429,
        "result": "API Error: 429 rate limit exceeded",
    }
)


def _claude():
    return load_adapters(ADAPTER_DIR)["claude"]


def _outcome(raw: str) -> SpawnResult:
    adapter = _claude()
    result = normalize(raw, envelope=adapter.envelope, structured_output=True)
    return SpawnResult(
        argv=["claude"],
        exit_code=1,
        stdout=raw,
        stderr="",
        duration_s=1.0,
        timed_out=False,
        result=result,
        failure_reason="exit 1",
        orphans_suspected=False,
    )


def test_the_captured_failure_classifies_as_auth():
    assert failures.classify(_outcome(CAPTURED), _claude()) == failures.AUTH


def test_the_marker_survives_normalization_into_the_payload():
    """classify() reads the parsed payload, not raw stdout. The auth object
    fails the claim schema, so this checks the failing result still carries
    the payload the marker is keyed on."""
    outcome = _outcome(CAPTURED)
    assert outcome.result.succeeded is False
    assert outcome.result.payload is not None
    assert outcome.result.payload["result"] == "Not logged in · Please run /login"


def test_a_rate_limit_is_not_an_auth_failure():
    """The reason the marker is not `is_error` or `terminal_reason`: both are
    identical here. Classifying this as auth would stop dispatching a friend
    that only needed to wait."""
    assert failures.classify(_outcome(RATE_LIMITED), _claude()) == failures.UNKNOWN


def test_an_unparseable_failure_is_not_auth():
    assert failures.classify(_outcome("connection reset by peer"), _claude()) == failures.UNKNOWN


def test_a_timeout_is_never_auth_even_carrying_the_marker():
    outcome = _outcome(CAPTURED)
    outcome.timed_out = True
    assert failures.classify(outcome, _claude()) == failures.UNKNOWN


def test_the_remediation_names_the_keychain_constraint():
    """A confined claude cannot reach its own credentials, so "run /login"
    alone would send a reader in circles."""
    remediation = _claude().auth.remediation
    assert "login" in remediation and "Keychain" in remediation


def test_a_successful_run_is_never_classified():
    outcome = _outcome(CAPTURED)
    outcome.failure_reason = None
    assert failures.classify(outcome, _claude()) == failures.UNKNOWN


# Captured 2026-10-28 in run-20261028T124037-42d7aefc, round 1.
SPEND_LIMIT_MESSAGE = "You've hit your individual spend limit · run /usage-credits to ask your admin for a higher limit"
SPEND_LIMIT = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": 429,
        "api_error_origin": "first_party",
        "api_error": "usage_limit_reached",
        "result": SPEND_LIMIT_MESSAGE,
    }
)


def _replay(raw, tmp_path, *, exit_code=1):
    capture = tmp_path / "capture.json"
    capture.write_text(raw, encoding="utf-8")
    return spawn.run_process(
        [
            sys.executable,
            "-c",
            "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text()); sys.exit(int(sys.argv[2]))",
            str(capture),
            str(exit_code),
        ],
        None,
        10,
        tmp_path,
        envelope=_claude().envelope,
        structured_output=True,
    )


def test_captured_spend_exhaustion_exposes_provider_diagnosis_and_quota(tmp_path):
    outcome = _replay(SPEND_LIMIT, tmp_path)
    assert not outcome.result.succeeded
    assert outcome.provider_error == SPEND_LIMIT_MESSAGE
    assert failures.classify(outcome, _claude()) == failures.QUOTA
    remediation = failures.quota_downgrade("claude-security", _claude(), [])
    assert "/usage-credits" in remediation
    assert "admin" in remediation and "higher limit" in remediation


@pytest.mark.parametrize(
    "raw, classification",
    [
        (RATE_LIMITED, failures.UNKNOWN),
        (CAPTURED, failures.AUTH),
    ],
)
def test_quota_marker_does_not_reclassify_other_api_errors(raw, classification, tmp_path):
    outcome = _replay(raw, tmp_path)
    assert outcome.provider_error == json.loads(raw)["result"]
    assert failures.classify(outcome, _claude()) == classification


def test_successful_structured_claude_answer_has_no_provider_error(tmp_path):
    raw = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": {"no_findings": True, "findings": None},
            "result": "A clean answer",
        }
    )
    outcome = _replay(raw, tmp_path, exit_code=0)
    assert outcome.result.succeeded
    assert outcome.provider_error is None
    assert failures.classify(outcome, _claude()) == failures.UNKNOWN
