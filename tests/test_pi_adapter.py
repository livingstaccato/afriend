"""The pi adapter: dispatch wiring against the REAL declared TOML.

Envelope/capture coverage lives in test_envelope_fixtures.py, the same home
every other shipped adapter uses; auth-marker coverage lives in
test_auth_markers_pi.py.
"""

import pytest

from afriend import adapters
from afriend.authority import ExternalToolPolicy
from afriend.paths import ADAPTER_DIR


@pytest.fixture
def registry():
    return adapters.load_adapters(ADAPTER_DIR)


def _spec(**over):
    base = dict(
        name="pi-general-0",
        cli="pi",
        lens="general",
        model="glm-5.2",
        effort=None,
        scope="repo",
        timeout=900,
    )
    base.update(over)
    return adapters.FriendSpec(**base)


def _build(registry, tmp_path, **over):
    adapter = registry["pi"]
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("CHALLENGE THIS ARTIFACT")
    schema = tmp_path / "s.json"
    schema.write_text("{}")
    return adapter, *adapters.build_argv(
        adapter,
        _spec(**over),
        prompt,
        schema,
        external_tool_policy=ExternalToolPolicy.DENY,
    )


def test_pi_takes_its_prompt_on_stdin(registry, tmp_path):
    """stdin, the same reason as claude: a positional prompt is one argv
    element, and the artifact-under-review broke claude on the per-argument
    exec ceiling."""
    _adapter, argv, stdin_text, _cap = _build(registry, tmp_path)
    assert stdin_text == "CHALLENGE THIS ARTIFACT"
    assert "CHALLENGE THIS ARTIFACT" not in argv


def test_pi_argv_holds_the_measured_flag_set(registry, tmp_path):
    _adapter, argv, _stdin, capability = _build(registry, tmp_path)

    def seq(*s):
        """Whether `s` appears as consecutive argv elements -- asserting two
        tokens separately passes on an argv that emits them at opposite ends."""
        return any(list(argv[i : i + len(s)]) == list(s) for i in range(len(argv) - len(s) + 1))

    assert seq("--print", "--mode", "json")
    assert "--no-session" in argv and "--offline" in argv
    # The write-closing allowlist and --no-approve arrive as the adapter's
    # readonly flags: present for BOTH scopes, like claude's.
    assert seq("--no-approve", "--tools", "read,grep,find,ls")
    assert seq("--model", "glm-5.2")
    # The six denial flags arrive through the authority decision.
    for flag in ("--no-mcp", "--no-context-files", "--no-skills"):
        assert flag in argv
    assert capability.readonly is True
    assert capability.effort == "unverified"
    assert capability.schema is False


def test_pi_doc_scope_keeps_reads_minimal(registry, tmp_path):
    """Doc scope must carry the same transcript-ephemerality guarantees as
    repo scope: no doc_argv override exists for pi, so the argv is identical
    apart from scope-independent placement."""
    _a, argv_repo, _s, _c = _build(registry, tmp_path, scope="repo")
    _a, argv_doc, _s, _c = _build(registry, tmp_path, scope="doc")
    assert argv_repo == argv_doc


def test_pi_declares_the_confinement_it_measured(registry):
    """The --tools allowlist holds for writes (a write canary reported
    NO_WRITE_TOOL) and not for reads (/etc/hostname answered) -- so pi is
    readonly, not self-confining, and takes the OS sandbox like codex."""
    adapter = registry["pi"]
    assert adapter.readonly is True
    assert adapter.self_confines is False
    assert adapter.needs_os_confinement is True
    assert adapter.sandbox_readonly_workdir is True
    assert adapter.sandbox_write == ()
    # The grant set names pi's own credential/config files only. settings.json
    # is deliberately absent: with it missing, pi skips the settings lock and
    # a confined friend reads no operator settings at all.
    assert not any(p.endswith("settings.json") for p in adapter.sandbox_read)


def test_pi_deny_probe_is_a_capability_probe(registry):
    """The probe must end in --help (bounded by _SAFE_CAPABILITY_PROBE_ACTIONS)
    so a pi too old for the denial flags fails at parse time, not mid-run."""
    adapter = registry["pi"]
    assert adapter.external_tools == "deny-argv"
    assert adapter.deny_external_tools_probe_argv[-1] == "--help"
    assert set(adapter.deny_external_tools_probe_markers) <= set(
        adapter.deny_external_tools_probe_argv
    )


def test_pi_env_pass_stays_credential_free(registry):
    """Provider keys belong to the operator's --pass-env, per run. What rides
    by default is pi's documented outbound-request env plus the state-dir
    redirect -- never a provider token."""
    adapter = registry["pi"]
    assert not any(name.endswith("_API_KEY") for name in adapter.env_pass)
    assert {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "PI_CODING_AGENT_DIR"} <= set(adapter.env_pass)


def test_pi_declares_a_columns_model_listing(registry):
    adapter = registry["pi"]
    assert list(adapter.models_argv) == ["--list-models"]
    assert adapter.models_format == "columns"
