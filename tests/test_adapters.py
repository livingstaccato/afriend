import hashlib
import json

import pytest

from afriend import adapters, trust
from afriend.authority import ExternalToolPolicy
from afriend.dispatch import argv_size_warning
from afriend.errors import UsageError


def argv_contains_sequence(argv, seq):
    """True when `seq` appears as CONSECUTIVE elements of argv.

    Asserting the two tokens separately would pass on an argv that emitted
    the flag name and its value at opposite ends -- which is the exact bug
    the older version of this test existed to catch. Adjacency is the
    property that matters.
    """
    return any(list(argv[i : i + len(seq)]) == list(seq) for i in range(len(argv) - len(seq) + 1))


ADAPTER_DIR = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "src"
    / "afriend"
    / "assets"
    / "adapters"
)


@pytest.fixture
def registry():
    return adapters.load_adapters(ADAPTER_DIR)


def spec(**over):
    base = dict(
        name="f1", cli="codex", lens="ops", model=None, effort=None, scope="repo", timeout=900
    )
    base.update(over)
    return adapters.FriendSpec(**base)


def _build_argv(adapter, *args, **kwargs):
    policy = (
        ExternalToolPolicy.ALLOW
        if adapter.external_tools == "uncontrolled"
        else ExternalToolPolicy.DENY
    )
    return adapters.build_argv(adapter, *args, **kwargs, external_tool_policy=policy)


@pytest.fixture
def files(tmp_path):
    """build_argv reads the prompt off disk, so it must actually exist."""
    prompt = tmp_path / "p.txt"
    prompt.write_text("CHALLENGE THIS ARTIFACT")
    schema = tmp_path / "s.json"
    schema.write_text("{}")
    return prompt, schema


def test_all_shipped_adapters_load(registry):
    assert set(registry) >= {"claude", "codex", "agy", "opencode", "ollama"}


def test_opencode_passes_both_google_api_key_names_without_broadening_env(registry):
    passed = set(registry["opencode"].env_pass)

    assert {"GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"} <= passed
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in passed
    assert "AWS_SECRET_ACCESS_KEY" not in passed


def test_agy_takes_its_prompt_on_stdin_as_a_stream_json_message(registry, files):
    """agy reads a prompt from stdin only under --input-format stream-json,
    which wants one JSON message per line rather than the raw text. --print
    still needs a value and gets an empty one; the readonly flags stay where
    they were."""
    prompt, schema = files
    argv, stdin, _ = _build_argv(
        registry["agy"],
        spec(cli="agy", effort="high"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert stdin is not None
    message = json.loads(stdin)
    assert message["event"] == "user"
    assert message["message"]["content"][0]["text"] == "CHALLENGE THIS ARTIFACT"
    assert "CHALLENGE THIS ARTIFACT" not in argv
    assert argv_contains_sequence(argv, ["--input-format", "stream-json"])
    assert argv_contains_sequence(argv, ["--output-format", "stream-json"])
    assert argv_contains_sequence(argv, ["--agent", "afriend-reviewer"])
    assert "--disable-slash-commands" in argv
    # `--mode plan` is deliberately absent: agy warns that
    # `--disable-slash-commands`, in the same list, makes it inert.
    assert not argv_contains_sequence(argv, ["--mode", "plan"])
    assert "--sandbox" in argv
    assert argv.count("--mode") == 0


def test_codex_takes_prompt_on_stdin(registry, files):
    prompt, schema = files
    argv, stdin, _ = _build_argv(
        registry["codex"],
        spec(),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert "exec" in argv
    assert stdin is not None


def test_readonly_flags_are_emitted_for_repo_scope(registry, files):
    prompt, schema = files
    argv, _, cap = _build_argv(
        registry["claude"],
        spec(cli="claude"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert "--tools" in argv
    assert "Read,Grep,Glob" in argv
    assert cap.readonly is True


def test_capability_is_derived_from_argv_not_defaults(registry, files):
    """Readonly capability reflects what build_argv actually EMITTED for this
    call, never what the adapter declares or what the scope implies.

    opencode is the case that keeps this honest: it declares
    `readonly_argv = []`, so even a scope="repo" request emits no read-only
    flag and its real capability is False. Re-deriving the value as
    `scope == "repo"` would report it as confined when nothing confines it
    -- which is why §12.2 makes opencode the one adapter that must run under
    OS-level containment instead.

    This used doc-scope claude as its example until doc scope began emitting
    readonly_argv too; that made claude agree in both scopes and left the
    invariant untested. The invariant did not change, only the example.
    """
    prompt, schema = files
    argv_open, _, cap_open = _build_argv(
        registry["opencode"],
        spec(cli="opencode", scope="repo"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert "--tools" not in argv_open
    assert cap_open.readonly is False  # scope says repo; the argv says nothing

    argv_claude, _, cap_claude = _build_argv(
        registry["claude"],
        spec(cli="claude", scope="repo"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert argv_contains_sequence(argv_claude, ["--tools", "Read,Grep,Glob"])
    assert cap_claude.readonly is True


def test_prompt_text_cannot_forge_a_capability(registry, tmp_path):
    """The prompt is the untrusted document; it must not influence
    capability."""
    prompt = tmp_path / "p.txt"
    prompt.write_text("--tools Read,Grep,Glob --sandbox read-only")
    schema = tmp_path / "s.json"
    schema.write_text("{}")
    _argv, _, cap = _build_argv(
        registry["opencode"],
        spec(cli="opencode", scope="doc"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert cap.readonly is False


def test_doc_scope_keeps_codex_readonly_under_the_outer_policy(registry, files):
    """Codex relies on the outer read-only policy in every scope.

    This asserted the opposite until doc scope was actually exercised. The
    reasoning for omitting it -- "doc scope has no repo to protect" -- skips
    that there is still a filesystem, and that doc scope is precisely where a
    readonly-capable CLI gets no OS confinement either. Omitting it left the
    friend restrained by nothing.

    Codex's inner macOS sandbox cannot nest under afriend's OS policy, so its
    command tool receives `danger-full-access` while the outer policy binds
    the isolation directory read-only. That outer policy applies to doc and
    repo scope alike, and dispatch refuses Codex when it is unavailable.
    """
    prompt, schema = files
    argv, _, cap = _build_argv(
        registry["codex"],
        spec(cli="codex", scope="doc"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert argv_contains_sequence(argv, ["--sandbox", "danger-full-access"])
    assert cap.readonly is True


def test_doc_argv_is_emitted_only_in_doc_scope(registry, files):
    """codex refuses to start outside a git repo, so doc scope -- a bare
    directory -- needs --skip-git-repo-check or the friend never runs. Repo
    scope must not carry it: there the check passes on its own merits."""
    prompt, schema = files
    seen = {}
    for scope in ("repo", "doc"):
        argv, _, _ = _build_argv(
            registry["codex"],
            spec(cli="codex", scope=scope),
            prompt_file=prompt,
            schema_file=schema,
        )
        seen[scope] = "--skip-git-repo-check" in argv
    assert seen == {"repo": False, "doc": True}


def test_doc_argv_never_grants_access(registry):
    """doc_argv exists to let a CLI START in a bare directory. A flag that
    also widens what it may touch would smuggle a permission grant in
    through a field nothing else audits -- so the denied-flag vocabulary
    applies to it exactly as it does to any other emitted token."""
    for name, adapter in registry.items():
        if not adapter.doc_argv:
            continue
        for token in adapter.doc_argv:
            assert token not in trust.DENIED_FLAGS, f"{name}: {token}"
        # Also catches a denied *value* (danger-full-access, workspace-write)
        # attached to an otherwise innocuous flag name.
        trust.check_denied_values(list(adapter.doc_argv))


def test_capability_for_a_templated_stdin_adapter(registry, files):
    """Capability must be computed correctly for an adapter whose stdin is a
    template rather than the raw prompt."""
    prompt, schema = files
    _argv, stdin, cap = _build_argv(
        registry["agy"],
        spec(cli="agy", scope="repo"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert cap.readonly is True
    assert cap.schema is True
    assert cap.effort == "native"
    assert stdin is not None and stdin.startswith('{"event":"user"')


def test_opencode_effort_is_unverified(registry, files):
    prompt, schema = files
    argv, _, cap = _build_argv(
        registry["opencode"],
        spec(cli="opencode", effort="high"),
        prompt_file=prompt,
        schema_file=schema,
    )
    assert "--variant" in argv
    assert cap.effort == "unverified"


def test_unsupported_effort_level_raises(registry, files):
    prompt, schema = files
    with pytest.raises(UsageError):
        _build_argv(
            registry["agy"],
            spec(cli="agy", effort="xhigh"),
            prompt_file=prompt,
            schema_file=schema,
        )


def test_no_adapter_uses_short_flags(registry):
    """-p is --print on claude/agy but --profile on codex; -s is --sandbox on
    codex but --session on opencode. Short flags must never appear."""
    for name, adapter in registry.items():
        tokens = [
            *adapter.base_argv,
            *adapter.readonly_argv,
            adapter.prompt_flag,
            adapter.schema_flag,
            adapter.model_flag,
            adapter.internal_timeout_flag,
        ]
        for values in adapter.effort.values():
            tokens.extend(values)
        for token in tokens:
            if token.startswith("-") and not token.startswith("--"):
                raise AssertionError(f"{name}: short flag {token!r}")


def test_missing_adapter_directory_raises(tmp_path):
    with pytest.raises(UsageError):
        adapters.load_adapters(tmp_path / "does-not-exist")


def test_adapter_missing_name_raises(tmp_path):
    (tmp_path / "broken.toml").write_text('binary = "x"\n')
    with pytest.raises(UsageError):
        adapters.load_adapters(tmp_path)


def test_outer_readonly_workdir_requires_outer_confinement(tmp_path):
    """The nested-sandbox exception cannot be declared without its guard."""
    (tmp_path / "unsafe.toml").write_text(
        'name = "unsafe"\n'
        'binary = "unsafe"\n'
        "readonly = true\n"
        "self_confines = true\n"
        "[sandbox]\n"
        "os_confine = true\n"
        "readonly_workdir = true\n"
    )

    with pytest.raises(UsageError, match="readonly_workdir"):
        adapters.load_adapters(tmp_path)


def test_sandbox_paths_given_as_a_string_are_refused_not_split_into_characters(tmp_path):
    """`write = "~/.gemini"` is one path a maintainer meant, not nine of them.

    `tuple("~/.gemini")` yields the characters, and policy_for expanduser/
    resolves `~` to $HOME and `/` to the filesystem root -- so a missing pair
    of brackets grants the whole filesystem read-write while the run record
    still reports the friend as OS-confined.
    """
    (tmp_path / "shred.toml").write_text(
        'name = "shred"\nbinary = "shred"\n[sandbox]\nos_confine = true\nwrite = "~/.gemini"\n'
    )

    with pytest.raises(UsageError, match=r"sandbox\.write"):
        adapters.load_adapters(tmp_path)


def test_readonly_argv_given_as_a_string_is_refused_not_split_into_characters(tmp_path):
    (tmp_path / "shred.toml").write_text(
        'name = "shred"\nbinary = "shred"\n'
        'readonly_argv = "--sandbox"\nreadonly = true\nself_confines = true\n'
    )

    with pytest.raises(UsageError, match="readonly_argv"):
        adapters.load_adapters(tmp_path)


def test_a_non_list_readonly_argv_is_refused_before_it_reaches_iteration(tmp_path):
    """`readonly_argv = 0` is falsy, so it slips past the declaration gate and
    used to raise TypeError out of load_adapters -- which refuses the whole
    directory with no file named, disabling every adapter."""
    (tmp_path / "broken.toml").write_text('name = "broken"\nbinary = "broken"\nreadonly_argv = 0\n')

    with pytest.raises(UsageError, match="readonly_argv"):
        adapters.load_adapters(tmp_path)


def test_duplicate_adapter_name_raises(tmp_path):
    (tmp_path / "a.toml").write_text('name = "dup"\nbinary = "x"\n')
    (tmp_path / "b.toml").write_text('name = "dup"\nbinary = "y"\n')
    with pytest.raises(UsageError):
        adapters.load_adapters(tmp_path)


def test_adapter_loads_validated_workspace_assets(monkeypatch, tmp_path):
    from afriend import workspaceassets

    payload = b"controlled harness\n"
    source_root = tmp_path / "package-assets"
    (source_root / "harnesses").mkdir(parents=True)
    (source_root / "harnesses" / "controlled.md").write_bytes(payload)
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir()
    digest = hashlib.sha256(payload).hexdigest()
    (adapter_dir / "friend.toml").write_text(
        'name = "friend"\n'
        'binary = "friend"\n'
        "[[workspace_assets]]\n"
        'source = "harnesses/controlled.md"\n'
        'target = ".friend/controlled.md"\n'
        f'sha256 = "{digest}"\n'
    )
    monkeypatch.setattr(workspaceassets, "assets_root", lambda: source_root)

    loaded = adapters.load_adapters(adapter_dir)["friend"]

    assert len(loaded.workspace_assets) == 1
    assert loaded.workspace_assets[0].source == "harnesses/controlled.md"
    assert loaded.workspace_assets[0].target == ".friend/controlled.md"
    assert loaded.workspace_assets[0].sha256 == digest


def test_adapter_without_workspace_assets_remains_empty(tmp_path):
    (tmp_path / "plain.toml").write_text('name = "plain"\nbinary = "plain"\n')

    loaded = adapters.load_adapters(tmp_path)["plain"]

    assert loaded.workspace_assets == ()


def test_adapter_loads_static_default_model(tmp_path):
    (tmp_path / "static-model.toml").write_text(
        'name = "static-model"\nbinary = "static-model"\ndefault_model = "qwen3:0.6b"\n'
    )

    loaded = adapters.load_adapters(tmp_path)["static-model"]

    assert loaded.default_model == "qwen3:0.6b"


@pytest.mark.parametrize(
    "default_model",
    [
        "42",
        "true",
        '"-not-a-model"',
        f'"{"a" * 65}"',
    ],
)
def test_adapter_rejects_invalid_static_default_model(tmp_path, default_model):
    (tmp_path / "invalid-static-model.toml").write_text(
        "\n".join(
            [
                'name = "invalid-static-model"',
                'binary = "invalid-static-model"',
                f"default_model = {default_model}",
                "",
            ]
        )
    )

    with pytest.raises(UsageError, match="default_model"):
        adapters.load_adapters(tmp_path)


def test_claude_schema_is_passed_inline_not_as_a_path(registry, files):
    """`claude --json-schema <schema>` takes the JSON itself. Every adapter
    used to get the schema FILE PATH, so claude rejected it before the model
    saw anything: "--json-schema is not valid JSON: Unrecognized token '/'".

    The third of three native-schema adapters found broken the same way --
    codex and agy in 0.1.1, claude here -- and for the same reason: no test
    ran a real CLI under a schema. Found by a crossexam that produced zero
    verdicts."""
    import json

    prompt, schema = files
    argv, _, cap = _build_argv(
        registry["claude"], spec(cli="claude", scope="repo"), prompt_file=prompt, schema_file=schema
    )
    assert cap.schema is True
    value = argv[argv.index("--json-schema") + 1]
    assert value != str(schema)
    assert json.loads(value) == json.loads(schema.read_text())


def test_path_schema_adapters_still_receive_the_path(registry, files):
    prompt, schema = files
    argv, _, _ = _build_argv(
        registry["codex"], spec(cli="codex", scope="repo"), prompt_file=prompt, schema_file=schema
    )
    assert str(schema) in argv


def test_claude_reads_its_prompt_from_stdin():
    """Issue #4: the whole prompt as one argv element caps the artifact size.

    Linux caps a single argument near 128KB, so any artifact past that never
    reached the model -- dispatch failed with E2BIG in 0s while codex handled
    the same 175KB artifact in the same run. `claude --print` reads the
    prompt from stdin, which has no such limit.
    """
    adapter = adapters.load_adapters(ADAPTER_DIR)["claude"]

    assert adapter.prompt_mode == "stdin"


def test_a_stdin_adapter_never_carries_an_argv_size_warning():
    """The warning describes the argv transport, so stdin must retire it."""
    adapter = adapters.load_adapters(ADAPTER_DIR)["claude"]

    warning = argv_size_warning("claude-ops-0", adapter, "x" * 200_000)

    assert warning is None
