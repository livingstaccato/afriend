---
name: configure
description: Use for an explicit afriend setup or configuration request - direct selection ($afriend:configure), or a request naming afriend that asks to inspect or change guided setup, review profiles, provider defaults, model selection, or review-context policy. Do not change settings without an exact requested change, and do not use for generic configuration questions unrelated to afriend.
---

# afriend configure

Inspect persistent provider defaults with:

```bash
afriend providers list
```

`afriend providers list` reports persistent defaults; `afriend doctor` reports
effective readiness. Persistent provider defaults are user-owned configuration,
changed only for an exact user-requested change with `afriend providers enable`, `disable`,
`set-model`, or `clear-model`. Do not turn an observation or recommendation
into a persistent change.

Provider `set-model` is only one model-selection layer: invocation `--model`
and an explicit `--friend`/roster model take precedence; an adapter default
and then the provider CLI default fill any remaining gap. A named model is a
requested value passed to the provider, not verification of its backend model.
With no selected model, no `--model` is passed and the exact provider CLI
default remains unverified.

Distinguish persistent defaults from per-run `--enable-provider` and
`--disable-provider` overrides. External-tool authority is a third, separate
layer: provider selection follows effective configured defaults and external tools remain denied by
default unless the user explicitly supplies `--allow-external-tools=PROVIDER`
or global `--allow-external-tools=*`. That authority neither changes defaults
nor follows from provider enablement. Codex's advisory host role does not
alter these boundaries.

For first-session setup, preview exact local changes without writing:

```bash
afriend init --guided
afriend init --guided --default-profile balanced --enable-provider claude
afriend init --guided --apply --default-profile balanced --enable-provider claude
```

The preview reports built-in profiles, discovered provider readiness, the host
role, and the continuing external-tool denial. `--apply` writes only the
listed provider defaults, optional Ollama model, selected default profile, and
generated roster; it never dispatches friends or enables external tools.
Plain `afriend init` remains the direct roster-generation command.

Profiles are a separate persistent layer:

```bash
afriend profiles list
afriend profiles show quick
afriend profiles create focused --base quick --timeout 300
afriend profiles set-default focused
```

Custom profiles inherit a built-in or custom base and can hold only review-safe
mode, preset, lenses, `max_friends`, `require_friends`, timeout,
`qualification_policy`, and
round/iteration ceilings. They cannot encode a provider, `--friend`, model,
credential, environment forwarding, external-tool authority, unsafe arguments,
or sandbox exception. Make a persistent change only for the exact
user-requested selection; use `--profile NAME` for a per-run choice.

Built-in profiles map to modes: `quick` keeps one report fan-out, `balanced`
selects `crossexam`, and `thorough` selects `loop`. A persistent default lives
in `~/.config/afriend/session.json`; `afriend run <artifact> --profile NAME`
selects one for a single run. An explicit `--mode` wins over the profile's
mode, as do explicit safe run settings.

Qualification policy is review evidence, not provider authority: the default
`cross-provider` needs two provider families; `distinct-sessions` accepts two
fresh workers; `distinct-models` accepts two fresh workers with different
exact requested models. The last is not verification of provider backends.

## Review-context policy

Inspect the host-only review-context policy before changing it:

```bash
afriend context show
afriend context set --sources current-task --automatic-combine --ambiguity ask
```

`enabled` controls whether the host resolves review context. `sources` is
`current-task` or `recent-session`; the latter is still bounded to the host's
configured session window and host-visible explicit evidence. `automatic_combine`
controls whether an unambiguous plan/review plus one-repository change set may
be composed. `ambiguity` is `ask` (the default), `newest`, or `refuse`.
`newest` considers same-repository candidates only and announces its choice;
`refuse` requires an explicit source choice.

Make a persistent change only for an exact requested setting, for example
`afriend context set --disabled` or `afriend context set --ambiguity refuse`.
The policy does not grant repository, provider, external-tool, write,
sandbox, or CLI-session-history authority. It does not cause the CLI composer
to discover paths or dispatch a review.

## Model selection provenance

Model selection is resolved in this exact order: invocation `--model` > explicit
`--friend`/roster > provider `set-model` > adapter default > CLI default. A
named model is requested and passed to the provider; it is not verified as the
backend model that answered. When no model is selected, no `--model` is
passed; the exact model is not verified and the record says that provider's
CLI default. Under the default external-tools-denied policy, Codex receives
`--ignore-user-config`, so an unset model selects its built-in default rather
than user configuration. An explicit `--allow-external-tools=codex` does not
supply `--ignore-user-config`, so afriend makes no built-in-default claim for
that invocation.

For example, an explicit OpenCode model is a provider-specific request, not a
verified backend identity:

```bash
afriend run spec.md --friend opencode:security:openai/gpt-5.6-sol \
  --allow-external-tools=opencode
```

Without an explicit model, OpenCode is recorded as `OpenCode CLI default (no --model passed; exact model not verified)`: that is a provider CLI default, not a verified backend identity.

For one run, `--enable-provider NAME` and `--disable-provider NAME` override
those defaults during automatic discovery. Disabled providers are not
probed. A friend must be `ready` before it consumes `--max-friends` capacity:
other states include `reachable-unconfigured` (for example, Ollama without a
model), `unavailable`, `disabled`, `host-excluded`, and `policy-blocked`.
`afriend doctor` reports the effective state, policy layer, and remediation.

External tools are denied by default, separately from filesystem/process
confinement. Adapters must neutralize provider-managed tools, plugins, apps,
MCP servers, and built-in browser, computer, and web-search tools or become
`policy-blocked`. The required-value flag is
repeatable: use `--allow-external-tools=PROVIDER` for a provider or the
explicit global grant `--allow-external-tools=*`. Unknown, duplicate, or
mixed `*` plus provider grants are invalid, as is the old valueless form.
`--unsafe-extra-args` additionally requires the global `*` grant and its own
acknowledgement.

External-tool authority is independent of persistent and per-run provider
enable/disable selection. Grants do not change provider defaults. Security
grants are never restored by `--resume`: repeat the same normalized set
exactly on the current command line. Resume uses the saved repository scope
and rejects `--repo`; it cannot replace the original automatic or explicit
repository selection.
