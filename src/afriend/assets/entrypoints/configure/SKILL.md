---
name: configure
description: Use only through direct qualified selection ($afriend:configure) or explicit /afriend routing to inspect or explicitly change guided setup, review profiles, or provider defaults. Do not change settings without an exact requested change.
---

# afriend configure

Inspect persistent provider defaults with:

```bash
afriend providers list
```

`afriend providers list` reports persistent defaults; `afriend doctor` reports
effective readiness. Persistent provider defaults are user-owned configuration, changed only for an
exact user-requested change with `afriend providers enable`, `disable`,
`set-model`, or `clear-model`. Do not turn an observation or recommendation
into a persistent change.

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
mode, preset, lenses, `max_friends`, `require_friends`, timeout, and
round/iteration ceilings. They cannot encode a provider, `--friend`, model,
credential, environment forwarding, external-tool authority, unsafe arguments,
or sandbox exception. Make a persistent change only for the exact
user-requested selection; use `--profile NAME` for a per-run choice.

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
