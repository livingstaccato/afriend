# Model selection provenance

## Goal

Make a run say which model each friend will receive before dispatch, and say
where that choice came from.  A person must not have to infer whether a model
change was selected by afriend or silently chosen by a provider CLI.

Deliver the behavior as a complete, documented release: include the pending
Claude marketplace installation troubleshooting guide, synchronize the skill
projection, update the architecture documentation, and publish one versioned
release after verification.

## Problem

`FriendSpec.model` currently stores only an optional model identifier.  `None`
means afriend does not pass the adapter's model flag.  That is a valid and
intentional choice, but progress currently omits it and the report calls it
`inherited`.  In particular, the Codex adapter uses `--ignore-user-config`
under its normal confinement policy, so an unset model is the Codex CLI's
built-in default, not the caller's Codex configuration.  That default can
change when Codex changes, and afriend cannot reliably discover the exact
backend model without making an additional provider call.

This is not Codex-only behavior.  OpenCode and every present or future adapter
can use an omitted model flag.  The feature therefore uses adapter-neutral
terms and provider-specific wording only where it makes a concrete guarantee,
such as Codex's `--ignore-user-config` behavior.

## Selection order

For every resolved friend, keep the existing precedence and record the source
that won:

1. Invocation-wide `--model`.
2. The explicit model in a `--friend` argument or roster entry.
3. The provider model configured with `afriend providers set-model`.
4. The adapter/provider default: afriend sends no model flag.

An adapter may supply a non-empty static default in the future; that is still
an adapter default.  An absent model flag is not presented as a verified model
name.

## Startup contract

Immediately after run setup and before the first round, `afriend run` writes a
bounded, stderr-only roster summary.  It contains one line per friend with
its name, provider, requested model, and selection source.  Examples:

```
afriend: friends ready:
afriend:   codex-security-0 (codex) -- model: gpt-6-astra [provider setting]
afriend:   codex-architecture-1 (codex) -- model: Codex CLI default (no --model passed; exact model not verified) [CLI default]
```

The wording is deliberately exact:

- A configured identifier means afriend will pass that identifier to the
  adapter.  It is a requested model, not a claim that a provider actually
  served that exact backend.
- With no identifier, afriend names the provider default and says that the
  exact model is unverified.  For Codex, this means its built-in CLI default
  after `--ignore-user-config` is applied.
- OpenCode and other adapters receive the same truthful treatment: their
  startup line says `<provider> CLI default (no --model passed; exact model
  not verified)` unless afriend passed a named model.  They are never labelled
  with a Codex-specific default.

The summary precedes any potentially long-running dispatch.  It appears for
normal and resumed runs whenever friends are resolved for a new dispatch.
It remains on stderr so stdout continues to contain only the run directory.

## Persistence and reporting

Store the requested model and its provenance in the run's existing friend
metadata, which is the audit artifact intended for detailed run state.  The
human report table will replace the ambiguous `inherited` text with the same
safe provider-default wording and add a compact source column.

Lifecycle events remain intentionally minimal.  They will not contain model
identifiers or selection provenance, preserving their current privacy and
size contract.

## Data model

Add a small immutable model-selection value to the resolved friend data:

- `requested_model: str | None`
- `source: invocation | explicit_friend | roster | provider_setting | adapter_default | cli_default`

The resolved value is created once, before self-exclusion and dispatch, then
flows to progress rendering, run metadata, and report rendering.  Existing
adapter argv construction continues to consume the optional requested model;
the feature does not change command construction or model precedence.

## Compatibility and tests

Existing APIs accepting `FriendSpec(model=...)` remain compatible.  New tests
cover each selection source, global override precedence, the no-model Codex
wording, stderr-only startup output, report rendering, run metadata, resumes,
and the guarantee that lifecycle event schemas do not gain model data.

Documentation will describe the selection order and the meaning of an
unverified provider default, including the Codex-specific `--ignore-user-config`
behavior.  The architecture diagram will show selection provenance flowing
from configuration/arguments through roster resolution to progress and the
run report.

The release documentation also includes a small, standalone installation
troubleshooting page for a missing Claude marketplace manifest in a temporary
or incomplete checkout.  It distinguishes the Python CLI installation from a
Claude marketplace installation and gives the durable-checkout recovery
commands.  It does not describe or imply any project rename.

Before publishing, the package version, compatibility distributions, plugin
manifests, generated plugin projection, changelog, and release workflow must
agree.  The release uses the existing `vX.Y.Z` tag/title convention and ships
only after the full portable quality gate succeeds.
