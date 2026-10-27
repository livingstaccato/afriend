# pi friend: evidence record (2026-10-27)

Everything below was executed against **pi 1.4.0** (`/home/tim/.pi/agent/bin/pi`,
installed tree `~/.pi/agent/install/releases/1.4.0/`, provider `verda` with
models `glm-5.2`, `kimi-k3`). Probe artifacts live in `/tmp/afriend-pi-probe/`;
live-run artifacts under `~/.local/state/afriend/runs/`.

## Shipped shape

`src/afriend/assets/adapters/pi.toml` (+ synced copy
`plugins/afriend/skills/review/adapters/pi.toml`), envelope indexing extension in
`src/afriend/envelopes.py`, `columns` listing format in `src/afriend/models.py`,
display name in `src/afriend/modeldisplay.py`, provider-listing pool width in
`src/afriend/commands/providers.py`, tests: `tests/test_pi_adapter.py`,
`tests/test_auth_markers_pi.py`, `tests/fixtures/pi_*.ndjson`, plus extensions of
`test_envelope_fixtures.py`, `test_models_listing.py`, `test_roster.py`,
`test_sandbox.py`, `test_docs` README badge (2699 → 2720).

## Capability evidence

| Claim | Command (essentials) | Outcome | Artifact |
|---|---|---|---|
| JSONL event stream in print mode | `pi --print --mode json …` | `session` header first, strict JSONL, `message_end` events carry full messages | probe-basic.ndjson |
| Writes confined by tool allowlist | prompt asks to write a file under `--tools read,grep,find,ls --no-approve` | model reports NO_WRITE_TOOL, nothing created on disk | probe-write.ndjson |
| Reads NOT confined | prompt reads `/etc/hostname` | succeeds → `self_confines = false`, OS sandbox declared | probe-read-outside.ndjson |
| Context-file injection without deny flags | AGENTS.md canary in cwd | answer echoes canary | probe-canary-with.ndjson |
| Full deny set | six `--no-*` flags + canaries | system sections reduce to `['preamble','tools','rules','docs','cwd']`; SUPPRESS_OK | probe-canary-suppressed.* |
| MCP without `--no-mcp` | canary server in `.pi/mcp.json` | suppressed ✓ (also trust-gated in print mode) | probe-mcp-suppressed.ndjson |
| Effort honesty | `--thinking bogus` | warns and continues (off..max listed) → `effort_kind = "unverified"` | probe-model.stderr |
| `--offline` keeps model calls working | CONFINED probes | CONFINED_OK; only gates catalog refresh (verified vs source: `modelNetworkEnabled` gates refresh only) | confined*.stdout |
| Fresh agent dir footprint | run with new `PI_CODING_AGENT_DIR` | only `auth.json`, `models.json`, `models-store.json` (0600) | fresh-agent/ |
| `--no-session` ephemerality | fresh dir run | no residual session files | probe-fresh.* |
| `--list-models` shape | real call | padded table w/ header `provider model context …` → new `columns` format | probe-models.txt |
| Full bwrap confinement via afriend's own machinery | `confined_probe.py` w/ policy_for() | CONFINED_OK2; `/home/tim/.ssh/id_ed25519` absent in-namespace; writes to `~/.pi/agent` land in discarded tmpfs | confined-cwd/probe-exposure.txt |
| Probe argv parses | `pi <six flags> --help` | exit 0, markers present | pi-help.txt |

## Auth markers (§14, verbatim captures, twice each)

1. Credentials absent → exit 1, stderr:
   `No API key found for the selected model.` (fresh agent dir) and
   `No API key found for verda.` (operator dir, key unset).
   Marker: prefix `No API key found for` (stderr_contains).
   Artifacts: probe-authfail.ndjson/.stderr, probe-envfail.stderr.
2. Credentials rejected → exit **0** in JSON mode, stream carries
   `stopReason:"error"` + `errorMessage` beginning
   `401: {"message":"Authentication Error, …","type":"auth_error",…}`.
   Marker: `"type":"auth_error"` (provider_error_contains, matched post-decode).
   Artifacts: probe-auth401.ndjson/.stderr; test fixture
   `tests/fixtures/pi_failure_auth.ndjson` is the real capture reformatted.

Live end-to-end auth classification: `afriend run … --friend pi …` **without**
`--pass-env VERDA_API_KEY` halted deterministically with the AUTH remediation
message (run-20261027T123826-b5744299). With `--pass-env` both friends answered.

Deliberately **not** declared: a quota marker (no exhaustion was provoked;
guessed markers are worse than none — an exhausted pi friend classifies UNKNOWN
and the repeat rule stops it after two identical rounds).

## Live demos of the full pipeline

- **report mode**, two pi friends (`security@verda/glm-5.2`,
  `ops@verda/kimi-k3` — distinct models keep independence):
  run-20261027T123839-c44fa925 → 12 claims against a planted-defect cache
  design (found all four planted defect classes plus deeper ones:
  symlink-through-lock-overwrite, torn cache reads).
- **gate mode**, same roster + `--qualification-policy distinct-sessions`:
  run-20261027T124221-97679495 → round-2 judging by both pi friends, 13
  verdicts, states settled-upheld/unproven; downgrade ledger honestly notes
  "pi reports effort as unverified" and same-provider judging.
- **independent review of this branch's diff by pi** (the mandated
  pre-completion review): run-20261027T125543-cd6f6654, 4 claims —
  c-0002 (answer rules must gate stopReason) was REAL and is fixed in b52324f
  (rules now gate `message.stopReason == "stop"`; aborted-with-findings fixture
  proves rejection). c-0003 refuted (reviewer misread a bracket expression;
  suite green). c-0001 documents a pre-existing architecture property (a
  read-only friend's credential grant is readable by the friend; identical for
  claude/codex/agy) — logged below under gaps, no change. c-0004 points at
  duplicated pi.toml copies; the byte-identical projection is maintained by
  `check_plugin_sync.py` inside `make quality`, so the gap is test-vs-plugin
  scoping the reviewer could not see from doc scope.

## Gates

- `make test-fast`: 2668 passed / 1 failed — the failure is
  `test_diagram_gate`, pre-existing and environmental (host PlantUML
  1.2020.02 cannot render the committed sources; CI pins 1.2026.8).
- `make quality`: exit 0 with the project's pinned PlantUML 1.2026.8 ahead of
  `plantuml` on PATH (`/tmp/plantuml-pinned/bin`) to reproduce the CI pin;
  includes ruff, mypy strict, max-LOC, plugin-sync, version-sync,
  diagrams-check, wheel build + isolated install, release-alias checks, full
  pytest (-n 4), and the mutation probe. Second full run after the c-0002 fix
  also exit 0.

## Verification gaps, honestly

- **Quota marker**: not measured (would burn paid allowance); absent by design.
- **macOS Seatbelt Gate 4** for pi: not exercised here (no macOS host); the
  sandbox policy shape mirrors codex/agy and Gate 4 coverage for those applies.
- **Windows**: pi adapter inherits the platform machinery (Job Objects,
  msvcrt locking) but pi itself wasn't installed/tested on Windows here;
  `~/.pi/agent` grant paths expand through home resolution the same way as
  other adapters.
- **Provider model listing under filtered env**: `afriend providers models pi`
  prints nothing on hosts where models.json uses `$VAR` key indirection — the
  listing runs childenv-filtered and `--pass-env` is not a providers flag. The
  `columns` parser itself is unit-tested against the captured table shape.
- **c-0001 (credential echo through findings)**: pi-auth credentials granted
  read-only in the sandbox can be quoted by a compromised artifact into the
  findings channel; documented in pi.toml, identical property in every shipped
  confined adapter, flagged for architecture review rather than fixed here.

## Token/latency notes

Four live reviews + one gate run ≈ 11 bounded pi calls (2–6.5 min each on these
models); `--max-calls` was applied to every demo run.
