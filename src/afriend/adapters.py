"""Declarative per-CLI records and the argv they produce.

Adapters are data, not code, so adding a friend is adding a TOML file. The
awkward parts encoded here are all verified CLI behaviors rather than
speculation — see the spec's "verified invocation traps" section.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import tomllib
from typing import Any, Literal

from .adapterschema import (
    _string_list,
    _string_table,
    _validate_capability_probe,
    _validate_default_model,
)
from .authority import AuthorityDecision, ExternalToolPolicy, enforce
from .envelopes import Envelope, parse_envelope
from .errors import UsageError
from .workspaceassets import WorkspaceAsset, WorkspaceAssetAudit, parse_workspace_assets

ModelSource = Literal[
    "invocation",
    "explicit-friend",
    "roster",
    "provider-setting",
    "adapter-default",
    "cli-default",
    "recorded-unknown",
]
MODEL_SOURCES: frozenset[ModelSource] = frozenset(
    {
        "invocation",
        "explicit-friend",
        "roster",
        "provider-setting",
        "adapter-default",
        "cli-default",
        "recorded-unknown",
    }
)


@dataclass(frozen=True)
class AuthMarkers:
    """Where an adapter's structured output says "not authenticated".

    `paths` are dotted paths into the parsed payload, each with the value
    that means auth failure -- e.g. `("error.type", "authentication_error")`.
    `exit_codes` are statuses this CLI uses exclusively for auth.

    Both empty means "unclassifiable", which is the honest default until
    someone captures a real auth failure from that CLI.
    """

    paths: tuple[tuple[str, str], ...] = ()
    exit_codes: tuple[int, ...] = ()
    # Substrings of the CLI's own error message, as the envelope reports it.
    # This is where a provider states an exhausted quota: codex writes
    # "You've hit your usage limit..." to stdout as a structured error and
    # leaves stderr holding nothing but a banner.
    provider_error: tuple[str, ...] = ()
    # Substrings of stderr that mean auth failure. Allowed ONLY as a string
    # captured verbatim from a real failure of that CLI, never a guess at
    # what it might say: the first real capture (agy) carried the marker
    # nowhere else -- exit 1, shared with unrelated errors, and empty
    # stdout. See failures.py for why the substring must be the specific
    # one and not "auth".
    stderr: tuple[str, ...] = ()
    remediation: str = ""

    def declared(self) -> bool:
        return bool(self.paths or self.exit_codes or self.stderr or self.provider_error)


def parse_auth(data: dict[str, Any] | None) -> AuthMarkers:
    """Build AuthMarkers from an adapter TOML's `[auth]` table."""
    if not data:
        return AuthMarkers()
    paths = tuple(
        (str(rule["path"]), str(rule["equals"]))
        for rule in data.get("markers", [])
        if isinstance(rule, dict) and "path" in rule and "equals" in rule
    )
    codes = tuple(int(c) for c in data.get("exit_codes", []) if isinstance(c, int))
    stderr = tuple(str(s) for s in data.get("stderr_contains", []) if isinstance(s, str) and s)
    provider_error = tuple(
        str(s) for s in data.get("provider_error_contains", []) if isinstance(s, str) and s
    )
    return AuthMarkers(
        paths=paths,
        exit_codes=codes,
        stderr=stderr,
        provider_error=provider_error,
        remediation=str(data.get("remediation", "")),
    )


@dataclass(frozen=True)
class Adapter:
    name: str
    binary: str
    base_argv: list[str]
    prompt_mode: str  # stdin | trailing-arg | flag-value
    prompt_flag: str
    readonly_argv: list[str]
    schema_flag: str
    model_flag: str
    internal_timeout_flag: str
    effort_kind: str  # native | unverified | none
    # Whether schema_flag takes the schema TEXT rather than a path to it.
    # claude's `--json-schema <schema>` wants the JSON itself; handed a
    # path it fails before the model sees anything ("--json-schema is not
    # valid JSON: Unrecognized token '/'"). Declared, not inferred, for the
    # same reason as everything else here: the two forms are
    # indistinguishable from the flag's spelling.
    schema_inline: bool = False
    effort: dict[str, list[str]] = field(default_factory=dict)
    transport: str = "exec"  # exec | http
    endpoint: str = ""
    # Whether this CLI is asked (via a flag in base_argv, e.g.
    # --output-format json) to wrap its answer in structured output of its
    # own. Declared explicitly rather than inferred from base_argv/schema_flag
    # so that "did this adapter ask for structured output" never has to be
    # guessed by pattern-matching flag spellings -- see normalize.py's
    # `structured_output` parameter for what this drives.
    structured_output: bool = False
    # Declarative "where the answer lives inside the wrapper" (see
    # normalize.Envelope). None means the shape is unknown/unverified;
    # normalize() falls back to scanning stdout directly rather than
    # guessing one.
    envelope: Envelope | None = None
    # §12.2: paths this CLI genuinely needs to read when it runs under OS
    # confinement -- its configuration and credential locations. Declared
    # per-adapter rather than guessed, because a sandbox missing a
    # credential path does not fail loudly: the CLI starts, fails to
    # authenticate, and looks like a broken friend. `~` is expanded at
    # policy-construction time so these stay portable between machines.
    #
    # Empty is meaningful: an adapter that restrains itself never reaches
    # the sandbox at all. Having a readonly MODE is not that -- agy declares
    # one and is confined anyway, because its flags were measured and none
    # of them restricted anything. See `needs_os_confinement`.
    sandbox_read: tuple[str, ...] = ()
    # §12.2: paths this CLI must WRITE to in order to start at all, outside
    # its isolation directory. opencode earned one by dying without a
    # writable log directory, and then stopped needing it once
    # `childenv.private_dirs` pointed its state at a private directory
    # beside the isolation directory instead. Redirecting a CLI's own notion
    # of where state lives beats punching a hole in the boundary, so reach
    # for this only when redirection has failed -- codex and agy are the two
    # that have, for token refresh and session state.
    #
    # A grant here is the whole subtree, and it OUTLIVES the run. Weigh what
    # the friend could leave behind in it: a path that decides what the CLI
    # executes on its next launch is a worse grant than a scratch directory,
    # however similar they look in this list.
    sandbox_write: tuple[str, ...] = ()
    sandbox_access_failure_stderr: tuple[str, ...] = ()
    # A provider can rely on the outer OS policy for read-only enforcement
    # when its own command sandbox cannot nest inside that policy.
    #
    # These two say what was MEASURED against the installed CLI, and are
    # never inferred from the presence of flags. That inference is what
    # handed agy an exemption from OS confinement for four flags that
    # restricted nothing, and it could not tell them apart from claude's
    # `--tools` allowlist, which holds.
    #
    # `None` means "not stated" and reads as restricting nothing, which is
    # the safe direction: such an adapter is confined. load_adapters refuses
    # a TOML that declares `readonly_argv` while leaving either of these
    # unset, so `None` reaching here means an adapter with no flags at all
    # -- or an Adapter built in code, which bypasses the loader entirely.
    readonly: bool | None = None
    self_confines: bool | None = None
    sandbox_readonly_workdir: bool = False
    # Opt in to OS confinement even though this CLI has a read-only mode of
    # its own. A read-only flag stops a friend WRITING; it does nothing about
    # what it can read, so a self-confining CLI can still open ~/.ssh. The
    # opt-in is per adapter rather than blanket because confinement breaks a
    # CLI whose credentials the sandbox cannot reach -- claude keeps its own
    # in the macOS Keychain, and granting that would hand a friend every
    # credential the operator has. Set only for a CLI verified to run
    # confined with the grants above.
    sandbox_confine: bool = False
    # §14: where this CLI's own structured output says "not authenticated".
    # Empty means unclassifiable, which is the honest default until someone
    # captures a real auth failure -- guessing at stderr substrings is what
    # §14 explicitly rejects.
    auth: "AuthMarkers" = field(default_factory=lambda: AuthMarkers())
    # The same marker shape, for a different verdict. An exhausted quota is
    # not a broken credential: re-running fixes nothing, but a different
    # model on a separate allowance, or a different provider, may. Kept
    # apart from `auth` because auth aborts the whole run and this must not.
    quota: "AuthMarkers" = field(default_factory=lambda: AuthMarkers())
    # §12.2: environment variables this CLI genuinely needs when it runs
    # confined. Its own credentials, essentially -- §12.3 already accepts
    # that a friend can exfiltrate those. Everything else is withheld.
    env_pass: tuple[str, ...] = ()
    # Flags this CLI needs in DOC scope, where its working directory holds a
    # copy of the artifact and nothing else. Some CLIs refuse to start
    # outside a git repository at all, which makes doc scope unusable for
    # them -- and every friend is downgraded to doc scope whenever the
    # artifact is not inside one. Emitted only for doc scope, and never
    # anything that grants access: see the note in codex.toml.
    doc_argv: tuple[str, ...] = ()
    # Provider-managed integrations are a separate authority boundary from
    # filesystem confinement. A TOML that declares nothing stays unknown,
    # which is the fail-closed value; shipped adapters declare one explicitly.
    external_tools: str = "unknown"  # none | deny-argv | uncontrolled | unknown
    deny_external_tools_argv: tuple[str, ...] = ()
    external_tool_sources: tuple[str, ...] = ()
    # A no-model argv that proves this installed executable accepts the deny
    # flags, plus bounded markers expected in its help/version output.
    deny_external_tools_probe_argv: tuple[str, ...] = ()
    deny_external_tools_probe_markers: tuple[str, ...] = ()
    # stdin only. A CLI that reads a prompt from stdin does not necessarily
    # read it as plain text: agy accepts one under --input-format stream-json,
    # which wants a JSON message per line. The template carries `{prompt}`
    # exactly once and the prompt is substituted JSON-encoded, so nothing in
    # an artifact can break out of the string it lands in. Empty means the
    # prompt is written verbatim, which is what every other adapter wants.
    stdin_template: str = ""
    # How to ask this CLI what models it offers, and how to read the answer.
    # Empty argv means the CLI has no such command -- codex is the case, and
    # saying so is better than presenting a guess as an inventory.
    #
    # `lines`: one id per line (opencode).
    # `tsv`:   id, a tab, then a human label; lines without a tab are the
    #          CLI's own progress chatter and are skipped (agy prints
    #          "Fetching available models..." first).
    models_argv: tuple[str, ...] = ()
    models_format: str = "lines"  # lines | tsv
    workspace_assets: tuple[WorkspaceAsset, ...] = ()
    # An adapter may declare a static model that afriend should pass unless
    # a stronger source selects one. Shipped adapters intentionally leave
    # this unset and defer to their own CLI defaults.
    default_model: str | None = None

    @property
    def is_readonly(self) -> bool:
        """Whether the adapter's complete dispatch policy prevents writes.

        `None` reaches here only for an adapter that declares no
        `readonly_argv` at all -- one declaring flags must say explicitly
        whether they work (see load_adapters). Claiming nothing means
        restricting nothing, which is the safe reading: such a friend is
        OS-confined.
        """
        return False if self.readonly is None else self.readonly

    @property
    def is_self_confining(self) -> bool:
        """Whether the provider's own argv provides the write restriction.

        Never inferred from the presence of flags. That inference handed agy
        an exemption from OS confinement for four flags that restricted
        nothing, and could not distinguish them from claude's `--tools`
        allowlist, which holds.
        """
        return False if self.self_confines is None else self.self_confines

    @property
    def needs_os_confinement(self) -> bool:
        """Whether dispatch requires an OS sandbox before it runs this friend.

        The single predicate dispatch decides with. Anything that asks
        `is_readonly` instead gets a different answer for agy, which has a
        read-only mode AND opts into confinement: true here, and true for
        `is_readonly`, so a check written as `not is_readonly` drops it --
        which is how agy came to be missing from the downgrade notes that
        name whose filesystem is unconfined.
        """
        return not self.is_self_confining or self.sandbox_confine

    def confinement_reason(self, *, subject: str | None = None) -> str:
        """Why the OS must confine this friend, in the operator's terms.

        Lived twice -- dispatch's refusal and the guided roster's note -- in
        two wordings free to drift apart as the four `is_readonly` copies
        did. `subject=None` gives the pronoun form for a sentence that has
        already named the friend; naming one gives the standalone form
        dispatch's refusal needs, quoted verbatim in troubleshooting.md.

        The true branch is agy: it HAS a read-only mode whose flags were
        measured to restrict nothing, so "no read-only mode" there would
        contradict both `afriend doctor` and report.md on the same host.
        """
        if self.is_readonly:
            if subject is None:
                return "its own flags do not confine it"
            return f"{subject}'s own flags do not confine it"
        if subject is None:
            return "it has no read-only mode"
        return f"{subject} has no read-only mode"


@dataclass(frozen=True)
class Capability:
    schema: bool
    readonly: bool
    effort: str  # native | unverified | none
    external_tools: str = "unknown"
    external_tool_sources: tuple[str, ...] = ()
    deny_external_tools_argv: tuple[str, ...] = ()
    workspace_assets: tuple[WorkspaceAssetAudit, ...] = ()


@dataclass(frozen=True)
class FriendSpec:
    name: str
    cli: str
    lens: str
    model: str | None
    effort: str | None
    scope: str  # repo | doc
    timeout: int
    independent: bool = True
    host_self_review: bool = False
    model_source: ModelSource = "cli-default"
    fresh_host_worker: bool = False


def capability_from_authority(adapter: Adapter, authority: AuthorityDecision) -> Capability:
    """Project adapter declarations and an enforced decision into audit capability."""
    return Capability(
        schema=bool(adapter.schema_flag),
        readonly=adapter.is_readonly,
        effort=adapter.effort_kind,
        external_tools=authority.status,
        external_tool_sources=authority.sources,
        deny_external_tools_argv=authority.argv,
    )


def load_adapters(directory: Path) -> dict[str, Adapter]:
    directory = Path(directory)
    if not directory.is_dir():
        raise UsageError(f"adapter directory not found: {directory}")

    registry: dict[str, Adapter] = {}
    sources: dict[str, Path] = {}
    for path in sorted(directory.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if "name" not in data:
            raise UsageError(f"{path}: adapter TOML is missing required field 'name'")
        name = data["name"]
        if name in registry:
            raise UsageError(
                f"duplicate adapter name {name!r}: declared in both {sources[name]} and {path}"
            )
        sources[name] = path
        external_tools = data.get("external_tools", "unknown")
        deny_argv = data.get("deny_external_tools_argv", [])
        tool_sources = data.get("external_tool_sources", [])
        probe_argv = data.get("deny_external_tools_probe_argv", [])
        probe_markers = data.get("deny_external_tools_probe_markers", [])
        sandbox_data = data.get("sandbox", {})
        if not isinstance(sandbox_data, dict):
            raise UsageError(f"{path}: sandbox must be a table")
        access_failure_stderr = sandbox_data.get("access_failure_stderr", [])
        readonly_argv = _string_list(path, "readonly_argv", data.get("readonly_argv", []))
        sandbox_read = _string_list(
            path, "sandbox.read", sandbox_data.get("read", []), nonempty=True
        )
        sandbox_write = _string_list(
            path, "sandbox.write", sandbox_data.get("write", []), nonempty=True
        )
        base_argv = _string_list(path, "base_argv", data.get("base_argv", []))
        doc_argv = _string_list(path, "doc_argv", data.get("doc_argv", []))
        models_argv = _string_list(path, "models_argv", data.get("models_argv", []))
        effort_levels = _string_table(path, "effort", data.get("effort", {}))
        env_data = data.get("env", {})
        if not isinstance(env_data, dict):
            raise UsageError(f"{path}: env must be a table")
        # The allowlist deciding what a confined child inherits.
        # `pass = "AWS_SECRET_ACCESS_KEY"` became 21 single-character names:
        # not a leak, but it silently withheld the variable someone meant.
        env_pass = _string_list(path, "env.pass", env_data.get("pass", []), nonempty=True)
        transport = data.get("transport", "exec")
        default_model = _validate_default_model(path, data.get("default_model"))
        workspace_assets = parse_workspace_assets(
            data.get("workspace_assets", []), transport=transport
        )
        if not isinstance(external_tools, str) or external_tools not in {
            "unknown",
            "none",
            "deny-argv",
            "uncontrolled",
        }:
            raise UsageError(f"{path}: invalid external_tools declaration")
        if not isinstance(deny_argv, list) or not all(
            isinstance(value, str) for value in deny_argv
        ):
            raise UsageError(f"{path}: deny_external_tools_argv must be a list of strings")
        if not isinstance(tool_sources, list) or not all(
            isinstance(value, str) and value for value in tool_sources
        ):
            raise UsageError(f"{path}: external_tool_sources must be a list of strings")
        if not isinstance(probe_argv, list) or not all(
            isinstance(value, str) for value in probe_argv
        ):
            raise UsageError(f"{path}: deny_external_tools_probe_argv must be a list of strings")
        if not isinstance(probe_markers, list) or not all(
            isinstance(value, str) and value for value in probe_markers
        ):
            raise UsageError(f"{path}: deny_external_tools_probe_markers must be a list of strings")
        if not isinstance(access_failure_stderr, list) or not all(
            isinstance(value, str) and value and "\n" not in value and "\r" not in value
            for value in access_failure_stderr
        ):
            raise UsageError(f"{path}: sandbox access failure markers must be nonempty strings")
        stdin_template = data.get("stdin_template", "")
        if not isinstance(stdin_template, str):
            raise UsageError(f"{path}: stdin_template must be a string")
        if stdin_template:
            # A template that never names the placeholder would send the CLI
            # a well-formed message with no artifact in it. The friend would
            # answer something, and the run would record a review that
            # reviewed nothing -- so this is refused at load rather than
            # discovered in a report.
            if data.get("prompt_mode", "stdin") != "stdin":
                raise UsageError(f"{path}: stdin_template requires prompt_mode = 'stdin'")
            placed = stdin_template.count(PROMPT_PLACEHOLDER)
            if placed != 1:
                raise UsageError(
                    f"{path}: stdin_template must contain {PROMPT_PLACEHOLDER} exactly once, "
                    f"found {placed}"
                )
            probe = stdin_template.replace(PROMPT_PLACEHOLDER, json.dumps("probe"))
            try:
                json.loads(probe)
            except ValueError as exc:
                raise UsageError(
                    f"{path}: stdin_template must be valid JSON once the prompt is "
                    f"substituted: {exc}"
                ) from exc
        models_format = data.get("models_format", "lines")
        if models_format not in {"lines", "tsv"}:
            raise UsageError(f"{path}: models_format must be 'lines' or 'tsv'")
        readonly = data.get("readonly")
        self_confines = data.get("self_confines")
        sandbox_confine = sandbox_data.get("os_confine", False)
        readonly_workdir = sandbox_data.get("readonly_workdir", False)
        if readonly is not None and not isinstance(readonly, bool):
            raise UsageError(f"{path}: readonly must be a boolean")
        if self_confines is not None and not isinstance(self_confines, bool):
            raise UsageError(f"{path}: self_confines must be a boolean")
        if not isinstance(sandbox_confine, bool):
            raise UsageError(f"{path}: sandbox.os_confine must be a boolean")
        if not isinstance(readonly_workdir, bool):
            raise UsageError(f"{path}: sandbox.readonly_workdir must be a boolean")
        # This is the sole route that permits an adapter's otherwise-denied
        # `--sandbox danger-full-access`: the workdir is protected by the
        # outer OS policy instead. Require every leg explicitly so a custom
        # adapter cannot claim the exception while skipping that policy.
        # A CLI's restriction flags must be VERIFIED, not assumed. These two
        # properties used to fall back to `bool(readonly_argv)` when unset,
        # so declaring flags was the same as declaring that they worked --
        # and agy shipped four that restricted nothing, buying a real
        # exemption from OS confinement with them. Nothing in the format
        # asked whether anyone had checked, so nothing could tell those apart
        # from claude's `--tools` allowlist, which does hold.
        #
        # Refused rather than defaulted, in either direction: defaulting to
        # trusted rebuilds the hole, and defaulting to untrusted would
        # silently confine a CLI whose credentials the sandbox cannot reach
        # (claude's live in the macOS Keychain). Someone has to say.
        if readonly_argv and (readonly is None or self_confines is None):
            raise UsageError(
                f"{path}: an adapter declaring readonly_argv must also declare "
                "`readonly` and `self_confines`. Their presence is not evidence that "
                "they work: state what was measured against the installed CLI."
            )
        if readonly_workdir and not (
            sandbox_confine and readonly is True and self_confines is False
        ):
            raise UsageError(
                f"{path}: sandbox.readonly_workdir requires os_confine=true, "
                "readonly=true, and self_confines=false"
            )
        if external_tools == "deny-argv" and not deny_argv:
            raise UsageError(
                f"{path}: external_tools='deny-argv' requires deny_external_tools_argv"
            )
        if external_tools == "deny-argv" and (not probe_argv or not probe_markers):
            raise UsageError(
                f"{path}: external_tools='deny-argv' requires a capability probe and markers"
            )
        if probe_argv:
            _validate_capability_probe(path, probe_argv, probe_markers)
        if external_tools != "deny-argv" and deny_argv:
            raise UsageError(
                f"{path}: deny_external_tools_argv is only valid with external_tools='deny-argv'"
            )
        if external_tools != "deny-argv" and (probe_argv or probe_markers):
            raise UsageError(
                f"{path}: deny capability probe is only valid with external_tools='deny-argv'"
            )
        registry[name] = Adapter(
            name=name,
            binary=data.get("binary", ""),
            base_argv=list(base_argv),
            prompt_mode=data.get("prompt_mode", "stdin"),
            prompt_flag=data.get("prompt_flag", ""),
            stdin_template=stdin_template,
            models_argv=tuple(models_argv),
            models_format=models_format,
            readonly_argv=list(readonly_argv),
            schema_flag=data.get("schema_flag", ""),
            schema_inline=bool(data.get("schema_inline", False)),
            model_flag=data.get("model_flag", ""),
            internal_timeout_flag=data.get("internal_timeout_flag", ""),
            effort_kind=data.get("effort_kind", "none"),
            effort=effort_levels,
            transport=transport,
            endpoint=data.get("endpoint", ""),
            sandbox_read=tuple(sandbox_read),
            sandbox_write=tuple(sandbox_write),
            sandbox_access_failure_stderr=tuple(access_failure_stderr),
            sandbox_confine=sandbox_confine,
            readonly=readonly,
            self_confines=self_confines,
            sandbox_readonly_workdir=readonly_workdir,
            auth=parse_auth(data.get("auth")),
            quota=parse_auth(data.get("quota")),
            env_pass=tuple(env_pass),
            doc_argv=tuple(doc_argv),
            structured_output=bool(data.get("structured_output", False)),
            envelope=parse_envelope(data.get("envelope")),
            external_tools=external_tools,
            deny_external_tools_argv=tuple(deny_argv),
            external_tool_sources=tuple(tool_sources),
            deny_external_tools_probe_argv=tuple(probe_argv),
            deny_external_tools_probe_markers=tuple(probe_markers),
            workspace_assets=workspace_assets,
            default_model=default_model,
        )
    return registry


def build_argv(
    adapter: Adapter,
    spec: FriendSpec,
    prompt_file: Path,
    schema_file: Path,
    external_tool_policy: ExternalToolPolicy,
) -> tuple[list[str], str | None, Capability]:
    """Return (argv, stdin_text, capability).

    Flag order matters: for adapters whose prompt is a flag *value*, every
    other flag must precede it, because a flag appearing after the prompt flag
    is swallowed as the prompt and the real prompt becomes an ignored
    positional — with a zero exit status.

    Capability is computed from the flags this function actually decides to
    emit, never by scanning the finished argv. The prompt text placed into
    that argv is the untrusted document under review; a document that
    happens to contain a flag's literal text (e.g. "Read,Grep,Glob") must
    not be able to forge a capability by being present in the argv list.
    """
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    # The resolved path, not the bare declared name. Windows' CreateProcess
    # does not itself retry PATHEXT the way shutil.which does, so a bare
    # "claude"/"codex"/"agy" -- installed as a .cmd/.ps1 shim, the normal
    # shape for an npm/node-based CLI on Windows -- raises FileNotFoundError
    # from Popen even though `which` resolves it. Falls back to the bare name
    # when `which` finds nothing, so the existing "binary not found" message
    # from spawn.run_process still names the declared binary.
    resolved_binary = shutil.which(adapter.binary) if adapter.binary else None
    argv = [resolved_binary or adapter.binary, *adapter.base_argv]
    authority = enforce(adapter, external_tool_policy)

    # A friend never needs to write, in EITHER scope: it reads the artifact
    # (plus, at repo scope, the checkout) and returns findings on stdout.
    #
    # Doc scope used to omit this on the reasoning that there is no repo to
    # protect. There is still a filesystem. Doc scope is also exactly where
    # a readonly-capable CLI gets no OS confinement either, so omitting it
    # left the friend unconfined by anything at all. Measured against the
    # real codex in a bare directory with no --sandbox flag: asked to write
    # outside its working directory, it did so on the first attempt.
    readonly_emitted = bool(adapter.readonly_argv)
    if readonly_emitted:
        argv += adapter.readonly_argv
    if spec.scope == "doc":
        # Never anything that grants access -- these exist because a CLI may
        # refuse to START outside a git repository, and doc scope is a bare
        # directory. See codex.toml for the one case and its evidence.
        argv += adapter.doc_argv

    schema_emitted = bool(adapter.schema_flag)
    if schema_emitted:
        schema_value = (
            Path(schema_file).read_text(encoding="utf-8")
            if adapter.schema_inline
            else str(schema_file)
        )
        argv += [adapter.schema_flag, schema_value]

    if spec.model and adapter.model_flag:
        argv += [adapter.model_flag, spec.model]
    if spec.effort:
        if spec.effort not in adapter.effort:
            raise UsageError(
                f"{adapter.name} does not support effort {spec.effort!r} "
                f"(available: {sorted(adapter.effort) or 'none'})"
            )
        argv += adapter.effort[spec.effort]
    if adapter.internal_timeout_flag:
        # The CLI's own timeout is set explicitly rather than inherited, so it
        # cannot silently disagree with the runner's kill deadline.
        argv += [adapter.internal_timeout_flag, f"{spec.timeout}s"]

    # Emitted while argv is still entirely options. Prompt placement below
    # may append an untrusted trailing argument or a prompt flag/value pair.
    argv += authority.argv

    capability = capability_from_authority(adapter, authority)

    if adapter.prompt_mode == "stdin":
        return argv, encode_stdin_prompt(adapter, prompt), capability
    if adapter.prompt_mode == "trailing-arg":
        return [*argv, prompt], None, capability
    if adapter.prompt_mode == "flag-value":
        return [*argv, adapter.prompt_flag, prompt], None, capability
    raise UsageError(f"unknown prompt_mode {adapter.prompt_mode!r}")


PROMPT_PLACEHOLDER = "{prompt}"


def encode_stdin_prompt(adapter: Adapter, prompt: str) -> str:
    """Wrap the prompt in whatever shape this CLI reads on stdin.

    `json.dumps` produces the quoted, escaped literal that replaces the
    placeholder, so the template's own JSON stays well-formed whatever the
    artifact contains -- an artifact holding a quote, a brace or a newline is
    data, and cannot become structure.
    """
    if not adapter.stdin_template:
        return prompt
    return adapter.stdin_template.replace(PROMPT_PLACEHOLDER, json.dumps(prompt)) + "\n"


def place_extra_args(argv: list[str], adapter: Adapter, extra_args: list[str]) -> list[str]:
    """Insert operator flags where a FLAG goes for this adapter's prompt mode.

    Appending them to the end was wrong for two of the five shipped adapters,
    and wrong in the way `build_argv`'s own docstring warns about: the prompt
    is not always last, and a token after it is not a flag any more.

    * `stdin` -- the prompt never enters argv, so the end is a flag position
      and nothing moves. codex.
    * `trailing-arg` -- the prompt IS the last element. Appending put the
      operator's flags after it, turning them into stray positionals and
      displacing the prompt from the position the CLI reads it from. claude.
    * `flag-value` -- the prompt is the value of `prompt_flag`. Appending put
      the flags after that value, where they are positionals rather than
      options. agy.

    So `--unsafe-extra-args` silently did nothing for agy and claude, or
    corrupted the invocation, rather than failing in a way anyone would see.
    Raised as a deadlocked claim by a cross-examination of dispatch.py --
    judges split because neither ran it; the argv settles it.
    """
    if not extra_args:
        return argv
    if adapter.prompt_mode == "trailing-arg" and argv:
        return [*argv[:-1], *extra_args, argv[-1]]
    if adapter.prompt_mode == "flag-value" and adapter.prompt_flag in argv:
        cut = argv.index(adapter.prompt_flag)
        return [*argv[:cut], *extra_args, *argv[cut:]]
    # stdin, or a shape this does not recognise: the end is a flag position.
    return [*argv, *extra_args]


def friend_key(spec: FriendSpec) -> str:
    """A friend's ledger identity: what round 1 writes into a claim's
    `origin`, and what judging matches against to decide who may judge
    what.

    Deliberately NOT `spec.name`: names carry a positional index
    (`codex-ops-0`) that the ledger does not, and a resumed or looped run
    must recognise its own earlier claims. The roster unit is
    `(cli, model, effort, lens)` (§8.1), so model and effort are part of the
    identity whenever they are set: two models on one CLI under one lens
    are two judges. They were one until a crossexam of verdicts.py showed
    what that cost -- quorum counted both, `latest_per_judge` kept one, and
    the order of `--friend` flags decided which, and so whether a gate
    cleared.
    """
    return _friend_key_values(spec.cli, spec.lens, spec.model, spec.effort)


def independent_friend_keys(specs: list[FriendSpec]) -> list[str]:
    """Unique ledger identities allowed to affect judging outcomes."""
    keys: list[str] = []
    for spec in specs:
        key = friend_key(spec)
        if spec.independent and key not in keys:
            keys.append(key)
    return keys


def _friend_key_values(cli: str, lens: str, model: str | None, effort: str | None) -> str:
    key = f"{cli}/{lens}"
    if model:
        key += f"@{model}"
    if effort:
        key += f"+{effort}"
    return key


def validate_roster_uniqueness(specs: list[FriendSpec], *, judging: bool) -> None:
    """Enforce the path-name and ledger-identity invariants of a final roster."""
    rows = [(spec.name, spec.cli, spec.lens, spec.model, spec.effort) for spec in specs]
    _validate_roster_identity_rows(rows, judging=judging)


def validate_roster_entry_uniqueness(entries: list[dict[str, Any]], *, judging: bool) -> None:
    """Enforce final-roster uniqueness before constructing ``FriendSpec`` objects."""
    rows = [
        (entry["name"], entry["cli"], entry["lens"], entry.get("model"), entry.get("effort"))
        for entry in entries
    ]
    _validate_roster_identity_rows(rows, judging=judging)


def _validate_roster_identity_rows(
    rows: list[tuple[str, str, str, str | None, str | None]], *, judging: bool
) -> None:
    names: set[str] = set()
    identities: dict[str, str] = {}
    for name, cli, lens, model, effort in rows:
        if name in names:
            raise UsageError(
                f"duplicate friend name {name!r}: names must be unique because "
                "they become output paths"
            )
        names.add(name)
        if not judging:
            continue
        key = _friend_key_values(cli, lens, model, effort)
        if key in identities:
            raise UsageError(
                f"friends {identities[key]!r} and {name!r} are the same friend -- "
                f"cli {cli!r}, lens {lens!r}, model {model!r}, effort "
                f"{effort!r} -- and would share one ledger identity ({key}); "
                "give one a different lens, model, or effort"
            )
        identities[key] = name
