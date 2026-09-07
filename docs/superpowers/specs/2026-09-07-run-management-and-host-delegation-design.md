# Run management and host delegation design

## Purpose

afriend retains a complete, private audit record for every review, but it has
no first-class way to inventory those records, deliberately remove old ones,
or turn a completed review into an implementation-oriented handoff.  Its
skills also need to distinguish the host's authority from a friend's
authority when a host considers launching workers.

This design adds small, explicit management commands and accurate host-facing
guidance.  It does not grant capabilities to the host, provider, or friend.

## Command contracts

### Run inventory

`afriend runs list [--out PATH] [--json]` is read-only.  It scans direct
children of the configured run root and reports only directories that have
the minimum recognizable run artifacts.  Each row carries a stable run id,
path, modification/start time when available, state, mode, scope, and report
path.  It never reads or renders captured prompts, raw completions, stderr,
or transcripts.

Unreadable, malformed, or non-run entries are represented as an inventory
warning in text/JSON rather than causing the usable entries to disappear.

### Retention

`afriend runs prune --older-than DAYS [--out PATH] --dry-run` selects only
completed run directories whose terminal metadata is older than the supplied
whole-number age.  The command defaults to a dry run; deletion requires an
explicit `--confirm` as well as an age selector.  Live, halted, malformed,
locked, and non-run directories are never selected.  Deletion is directory
scoped below the validated run root, and the output lists each selected run
and its reason.  There is no automatic cleanup policy and no silent default
retention limit.

### Status triage

`afriend status RUN` remains read-only.  Its structured summary gains a
`triage` object formed only from the canonical ledger and known artifact
paths: final finding IDs, severities/statuses when present, unresolved count,
and safe paths to `report.md`, `claims.jsonl`, and relevant per-friend
evidence files.  Human output presents a compact final-findings section.

The triage command never embeds prompt text, raw response text, stderr, or
other transcript contents.  If an old or incomplete run lacks a report or
ledger, the summary states that fact without manufacturing findings.

### Implementation handoff

`afriend plan RUN [--out PATH]` is read-only with respect to review state but
writes one new durable artifact: `PLAN.md` in the selected run directory.  It
builds a deterministic, claim-linked checklist from unresolved canonical
claims and links the report and evidence locations.  It labels itself a
proposal for the controlling AI/human to review.  It does not edit the target
repository, dispatch friends, add resolutions, change claim disposition, or
declare a fix verified.

If `PLAN.md` already exists, the command refuses rather than overwriting audit
history; a future explicit replacement design may add a separate command.
The plan artifact records its source run ID and the ledger/report inputs used
to generate it.

## Host delegation guidance

The canonical router and review skill will explain that afriend coordinates
independent reviewer processes while the invoking host remains responsible
for edits, commits, merges, and its own permission configuration.  Guidance
will provide two copyable patterns:

1. a read-only investigation worker that returns evidence; and
2. an isolated implementation worker that returns a diff and tests, while
   the host retains commit/push/merge authority.

It will state that a host permission classifier can refuse an autonomous
multi-file-edit-and-commit worker and that afriend cannot bypass that policy.
It will separately state that `--allow-external-tools` grants a provider's
managed tools for one afriend run only; it does not grant the host authority
to launch a worker.

## Security and compatibility

All new run inspection uses the existing root-bounded secure-I/O helpers and
never follows paths outside the selected run root.  Prune needs an explicit
destructive-operation implementation and tests for symlinks/locks/terminal
state.  Existing runs and `status` output remain usable: unavailable data is
represented as absent/unknown fields rather than an error.

The package remains stdlib-only.  Canonical assets are edited under
`src/afriend/assets/` and projected with `make plugin-sync-copy`; generated
plugin files are never edited directly.

## Verification

Tests cover parsing, inventory filtering, prune selection and confirmation,
safe refusal cases, status triage transcript redaction, durable plan
provenance/refusal-to-overwrite, and skill/document synchronization.
`make quality` remains the release gate.
