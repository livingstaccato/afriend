# Pi friend integration

## Outcome

Ship `pi` as a built-in friend with the same discovery, configuration,
roster selection, dispatch, status, resume, and review-mode behavior as the
existing CLI adapters. Keep the runtime stdlib-only.

## Approach

Use a canonical `assets/adapters/pi.toml` adapter and the existing execution
pipeline. Prefer declarative metadata; extend shared runtime interfaces only
where captured Pi behavior cannot be represented accurately. A dedicated RPC
client adds unnecessary lifecycle complexity. A minimal adapter without
behavioral verification does not meet the acceptance criteria.

The installed executable is Pi 1.4.0. Its help documents stdin-compatible
print mode, JSON event output, ephemeral sessions, model selection, thinking
levels, a read-only tool allowlist, and explicit switches disabling extensions,
MCP, skills, prompt templates, themes, and context-file discovery. These are
candidate controls, not proof that enforcement works.

## Invocation and authority

Send composed prompts through stdin to avoid argument-size limits. Use fresh,
noninteractive, ephemeral sessions. Select models with `--model` and map
supported effort levels through `--thinking`. Preserve CLI defaults when no
model is selected. Disable inherited executable customizations and external
tools explicitly, with a no-model capability probe for required flags.

Measure the effective tool set and attempted writes before declaring
read-only/self-confinement capabilities. Assess OS confinement and startup
credential/state dependencies through the existing policy machinery. Do not
grant broad home-directory access. Do not change the operator's configuration
or authentication while probing; use temporary state for destructive or
unauthenticated experiments. Record platform limits honestly.

## Responses and failures

Capture actual JSON events before defining answer extraction and terminal
completion. Exclude reasoning, user messages, and tool results from answers.
Handle multi-block text if Pi emits it. Classify authentication and quota
failures only from observed, specific markers; shared exit codes alone are
insufficient. Preserve existing timeout, cancellation, and process cleanup.

Model inventory must return usable model identifiers, including provider
qualification where necessary, or explicitly report an unsupported inventory
rather than misparse human output.

## Product coverage

Update current user-facing documentation and skill references, then regenerate
the plugin projection from canonical assets. Include the adapter in packaged
wheel verification. Audit provider-specific lists and host detection so Pi
participates in normal selection and independence rules without special CLI
aliases or a new skill.

## Acceptance evidence

1. Focused tests prove argv construction, authority enforcement, output
   extraction, actual failure shapes, discovery/configuration/model selection,
   and lifecycle behavior introduced by this integration.
2. Deterministic end-to-end tests exercise Pi through report, crossexam, gate,
   and loop, plus status/resume where adapter-specific behavior matters.
3. Live probes establish actual CLI behavior. A bounded live review against a
   seeded defective artifact demonstrates a normalized actionable finding.
   Exercise live multi-round judging as well as the initial review.
4. Run `make quality`, including plugin synchronization, wheel installation,
   typing, formatting, lint, and tests. Run available real Linux confinement
   checks and report any platform-specific coverage still unavailable.
5. Save a concise evidence report with exact commands, executable version,
   outcomes, and local run artifact locations. Never describe simulated tests
   as live proof or untested platforms as verified.

## Scope

No new runtime dependency, release/version bump, publishing, or unrelated
refactoring. A blocked live model call or unavailable platform must be
reported as an evidence gap, not counted as a successful verification.
