"""pi's auth markers, checked against its two real captured failure shapes (§14).

Both were provoked without touching real credentials, 2026-10-27, pi 1.4.0:

  Credentials absent -- PI_CODING_AGENT_DIR pointed at an empty directory, so
  pi found neither auth.json nor models.json: exit 1, nothing on stdout but
  the session header, stderr exactly:

      No API key found for the selected model.

      Use /login to log into a provider via OAuth or API key. See: ...

  (with a named provider the first line reads "No API key found for verda."
  -- hence the marker is the infillable prefix, not the whole sentence).

  Credentials present but rejected -- an apiKey the provider refuses
  (afriend-bad-key-000): exit 0, because with --mode json pi puts the failure
  in the stream instead of the exit status. The final assistant message has
  stopReason "error" and errorMessage starting "401: {" with the provider's
  own body embedded -- matching on the HTTP status alone would be sloppy (it
  is the auth shape the provider asserted, not pi's words), so the marker is
  the body's "type":"auth_error", a string a rate limit never contains.

There is deliberately NO quota marker: no real exhaustion was provoked (that
burns a paid allowance), and §14 forbids declaring markers from guesswork.
An exhausted pi friend therefore classifies UNKNOWN -- visible as a failure,
stopped after two identical rounds, and never mistaken for an auth abort.
"""

from pathlib import Path

from afriend import envelopes, failures
from afriend.adapters import load_adapters
from afriend.normalize import normalize
from afriend.paths import ADAPTER_DIR
from afriend.spawn import SpawnResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Verbatim first line of the two credential-free captures, with the
# provider-name infill pi itself used on this host.
STDERR_GENERIC = "No API key found for the selected model.\n"
STDERR_NAMED = "No API key found for verda.\n"
SESSION_HEADER = (
    '{"type":"session","version":3,"id":"01a17e00-0000-7000-8000-000000000320",'
    '"timestamp":"2026-10-27T16:50:07.877Z","cwd":"/home/tim/code/github/livingstaccato/afriend"}\n'
)


def _pi():
    return load_adapters(ADAPTER_DIR)["pi"]


def _outcome(raw: str, *, exit_code: int, stderr: str = "") -> SpawnResult:
    adapter = _pi()
    result = normalize(raw, envelope=adapter.envelope, structured_output=True)
    failure_reason = None
    if exit_code != 0:
        failure_reason = f"exit {exit_code}"
    elif not result.succeeded:
        failure_reason = "; ".join(result.errors) or "unusable output"
    provider_error = (
        envelopes.envelope_error(raw, adapter.envelope)
        if failure_reason is not None and adapter.envelope is not None
        else None
    )
    return SpawnResult(
        argv=["pi"],
        exit_code=exit_code,
        stdout=raw,
        stderr=stderr,
        duration_s=1.0,
        timed_out=False,
        result=result,
        failure_reason=failure_reason,
        orphans_suspected=False,
        provider_error=provider_error,
    )


def test_credential_free_stderr_classifies_as_auth_generic_and_named():
    for stderr in (STDERR_GENERIC, STDERR_NAMED):
        outcome = _outcome(SESSION_HEADER, exit_code=1, stderr=stderr)
        assert failures.classify(outcome, _pi()) == failures.AUTH


def test_the_captured_401_stream_classifies_as_auth_by_provider_error():
    raw = (FIXTURES / "pi_failure_auth.ndjson").read_text(encoding="utf-8")
    outcome = _outcome(raw, exit_code=0)
    assert failures.classify(outcome, _pi()) == failures.AUTH


def test_the_exit_status_alone_is_never_auth():
    """Exit 1 is shared with parse errors and unknown flags; exit 0 is shared
    with every failure under --mode json. Neither is a marker on its own."""
    outcome = _outcome(SESSION_HEADER, exit_code=1, stderr="Error: Unknown argument --mod")
    assert failures.classify(outcome, _pi()) == failures.UNKNOWN
    outcome = _outcome(SESSION_HEADER, exit_code=0, stderr="")
    assert failures.classify(outcome, _pi()) == failures.UNKNOWN


def test_an_error_turn_without_an_auth_shape_stays_unknown():
    """A rate-limiting provider would write a 429 in this exact envelope.
    Nothing pi declares should mistake that for a credential failure."""
    raw = (FIXTURES / "pi_failure_auth.ndjson").read_text(encoding="utf-8")
    # The needle lives INSIDE a JSON string in the stream, escaped on disk and
    # unescaped only after envelope extraction; swapping it on the raw text
    # therefore edits the escaped spelling, not the decoded one.
    rate_limited = raw.replace('\\"type\\":\\"auth_error\\"', '\\"type\\":\\"rate_limit_error\\"')
    assert rate_limited != raw
    outcome = _outcome(rate_limited, exit_code=0)
    assert failures.classify(outcome, _pi()) == failures.UNKNOWN


def test_a_turn_pi_killed_itself_is_not_auth():
    raw = (FIXTURES / "pi_turn_aborted.ndjson").read_text(encoding="utf-8")
    outcome = _outcome(raw, exit_code=0)
    assert failures.classify(outcome, _pi()) == failures.UNKNOWN


def test_the_remediation_names_what_the_sandbox_actually_grants():
    """A confined pi reads auth.json and models.json only -- telling an
    operator to just `pi --login` would leave a friend that still sees the
    failure under --pass-env-free dispatch."""
    remediation = _pi().auth.remediation
    assert "auth.json" in remediation and "--pass-env" in remediation
