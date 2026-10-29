# Five-worker, three-round cross-examination

**Outcome: incomplete, not release clearance.** The approved replacement roster
produced five usable critiques and attempted all three rounds / 15 calls.
Thirteen responses were usable. Pi/Kimi timed out in round 2; Codex security
reported selected-model capacity in round 3. The saved result remains exit 1.

| Round | Usable responses | Failure |
| --- | ---: | --- |
| 1 critique | 5 / 5 | None |
| 2 judging | 4 / 5 | Pi/Kimi call timeout |
| 3 judging | 4 / 5 | Codex selected-model capacity refusal |

The [retained JSON](2026-10-29-cross-examination.json) contains the actual
snapshot/artifact hashes, limits, all friend statuses and complete claim/verdict
ledger. The [frozen artifact](2026-10-29-cross-examination-artifact.md) records
what was reviewed; subsequent fixes and evidence updates do not rewrite it.
All five workers were fresh processes. Three Codex workers share a provider
family; OpenCode and Pi requested the same Kimi model. This is not evidence of
five independent backend models. OpenCode had document-only access. Pi's effective
thinking effort remains unverified by its adapter.

## Completeness and bounds

This attempt required `--require-friends 5`, used cross-provider qualification,
`--max-rounds 3`, `--max-calls 15`, `--timeout 600` and
`--max-wall-clock 3000`. A complete healthy run must reach a terminal state,
record the required usable participants, and have no missing required round
responses, timeout/orphan/truncation captures or exhausted ceiling. Record actual
round count; a three-round ceiling alone does not prove three rounds occurred.
A complete run can still contain disputed claims requiring review.

The machine result here is unambiguously incomplete: two failed friend rows,
one timed-out process capture, six deadlocked claims and two incomplete claims.
It must not be relabeled passed or combined with other runs to manufacture
quorum. The earlier Claude and GLM runs were preserved and superseded only after
the user's two explicit replacement choices. No further roster replacement or
waiver is automatic. A bounded retry versus retaining this inconclusive result
is awaiting the user's choice. Paid live calls are not part of `make quality`
or the automated publication workflow; their availability is not silently
substituted for deterministic CI/release checks.

## Host treatment of findings

Ledger states are retained. The host's source/test-based treatments below are
recorded separately and do not turn a failed judging run into clearance.

| Claims | Recorded result | Host treatment and evidence |
| --- | --- | --- |
| c-0001, c-0008 | Deadlocked / upheld | Specific historical friend-eval CI coverage gap fixed: full Git history, explicit two-case JUnit pass check, and required release-CI step. Actual cases pass; skipped/failed/error/missing/duplicate/wrong-name fault records are rejected. This is the eval fixture's provenance behavior, not all runtime artifact-integrity coverage. |
| c-0002 | Incomplete | Named paths/tests/variables exist; access to external CI evidence was limited for some judges. Retained source hashes, CI links, concrete variable names and five node IDs make scope explicit. Missing access is not refutation. |
| c-0003, c-0010 | Incomplete / deadlocked | Local evidence is now durably retained as a sanitized compressed log and source-hash manifest. The warning is identified below. |
| c-0004 | Deadlocked | Wording now says fault injections were correctly rejected; all five required containment node IDs are named in the audit. |
| c-0005 | Refuted | A top-level hold/pending status remains explicit. Green historical checks do not authorize production publication. |
| c-0006 | Deadlocked | Completeness, failed responses, call/time bounds, replacement choices and stop behavior are recorded above. The incomplete outcome has not been waived. |
| c-0007 | Deadlocked | Startup evidence is explicitly bound to its run and observed versions. Existing PR/main-push triggers recheck latest; captured versions can be reproduced with optional overrides. Continuous monitoring is not claimed. Default pinning would contradict the user's latest-by-default requirement; scheduled monitoring is a separate enhancement, not proof that the captured observations are false. Rerun checks before a delayed release or after harness changes. |
| c-0009 | Deadlocked | Wording now identifies the fixed targeted 16-mutant set across envelopes, adapters, failures, rounds, models and judgebatch. It does not claim repository-wide mutation coverage. |

## Preserved disagreement

The startup-monitoring claim illustrates why the ledger is not flattened into a
majority verdict:

**codex/security+low — amended**

> The lack of scheduled refresh and freshness enforcement is real. However, 'nothing ever re-triggers it' is false: pushes and pull requests to main rerun the jobs. Recorded versions also make the evidence more specific than an unidentified latest installation.

**opencode/spec-vs-reality@verda/kimi-k3 — unproven**

> The uncontested half is confirmed in the artifact: the startup jobs select 'latest' without an override, 'Versions are observations, not pins', and the captured versions (Claude 2.1.312, Codex 0.165.0, OpenCode 2.2.0, Pi 1.4.0) are point-in-time; release builds also 'require successful exact-commit push-to-main CI', which is at least consistent with a gate that consumes a past push-triggered run. But the claim's decisive mechanisms — that ci.yml has no scheduled trigger, that ci/provider_startup.py rejection_regex entries pin exact diagnostic strings, and that ci/verify_release_ci.py 'never re-runs' the startup jobs — live entirely in repository files that are not available here. The artifact neither describes any periodic re-validation nor proves its absence, so the silent-decay mechanism cannot be established or ruled out from what I can see.


## Deterministic follow-up

The subsequent candidate passed `make quality` with **2,948 passed, 36 skipped**
and **16 targeted mutants killed**, zero survivors/skips. Its
[retained log](2026-10-29-portable-quality.log.gz) and
[source-hash manifest](2026-10-29-portable-quality.json) identify that frozen
checkout, including uncommitted follow-ups rather than pretending HEAD alone
identifies a dirty candidate.

The single warning was a Python `DeprecationWarning` from
`tests/test_providerconfig.py::test_locked_update_rereads_changes_made_before_it_acquires`:
`multiprocessing` used `os.fork()` in a multithreaded process. It did not fail the
test. The final hosted candidate still needs its fresh CI result, including the
corrected real Windows unsafe-control/protected-interpreter regression.
