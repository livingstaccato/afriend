"""Targeted mutation probe for the provider transport and failure paths.

Not a general mutation runner: a fixed list of plausible wrong versions of
decisions this code makes, each paired with the tests that ought to notice.
A survivor means no test asserts that decision -- which is the only thing
a passing suite cannot tell you about itself.

Run with `make mutation-probe`, which `make quality` includes. A survivor
or a stale anchor fails the run: a probe that always exits 0 certifies
whatever it is pointed at.

Four of the first twelve survived, including the ordering between an
exhausted quota and a broken credential, and the case that motivated the
whole change: a real codex failure carries BOTH a noisy stderr and a
structured error, and every test supplied only one of them. A fifth was
hidden behind a renamed test file -- see `run()` on why pytest's exit code
has to be read rather than merely compared to zero.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (label, file, original, mutated, test paths)
MUTATIONS = [
    (
        "ndjson error: first event wins instead of last",
        "src/afriend/envelopes.py",
        "            if isinstance(value, str) and value.strip():\n                found = value.strip()\n    return found",
        "            if isinstance(value, str) and value.strip():\n                return value.strip()\n    return found",
        ["tests/test_provider_error.py"],
    ),
    (
        "ndjson error: error rules also feed the answer",
        "src/afriend/envelopes.py",
        "        for rule in envelope.error_rules:\n            if rule.match_value != type_value:",
        "        for rule in (*envelope.error_rules, *envelope.rules):\n            if rule.match_value != type_value:",
        ["tests/test_provider_error.py", "tests/test_envelope_fixtures.py"],
    ),
    (
        "terminal event: any parseable event ends the stream",
        "src/afriend/envelopes.py",
        "        if isinstance(parsed, dict) and parsed.get(envelope.match_field) == envelope.terminal_event:",
        "        if isinstance(parsed, dict):",
        [
            "tests/test_early_answer_stop.py",
            "tests/test_envelope_fixtures.py",
            "tests/test_spawn.py",
        ],
    ),
    (
        "terminal event: only the final line is scanned",
        "src/afriend/envelopes.py",
        "    for line in reversed(window.splitlines()[-TERMINAL_SCAN_LINES:]):",
        "    for line in reversed(window.splitlines()[-1:]):",
        ["tests/test_early_answer_stop.py"],
    ),
    (
        "terminal event: the whole buffer is rescanned every poll",
        "src/afriend/envelopes.py",
        "    window = strip_ansi(text[-TERMINAL_SCAN_BYTES:])",
        "    window = strip_ansi(text)",
        ["tests/test_early_answer_stop.py"],
    ),
    (
        "stdin template: prompt substituted raw, not JSON-encoded",
        "src/afriend/adapters.py",
        '    return adapter.stdin_template.replace(PROMPT_PLACEHOLDER, json.dumps(prompt)) + "\\n"',
        '    return adapter.stdin_template.replace(PROMPT_PLACEHOLDER, prompt) + "\\n"',
        ["tests/test_stdin_template.py", "tests/test_adapters.py"],
    ),
    (
        "stdin template: placeholder count not enforced",
        "src/afriend/adapters.py",
        "            if placed != 1:",
        "            if placed > 99:",
        ["tests/test_stdin_template.py"],
    ),
    (
        "classify: auth checked before quota",
        "src/afriend/failures.py",
        "    if adapter is not None and _matches(outcome, adapter.quota):\n        return QUOTA\n    if adapter is not None and _matches(outcome, adapter.auth):\n        return AUTH",
        "    if adapter is not None and _matches(outcome, adapter.auth):\n        return AUTH\n    if adapter is not None and _matches(outcome, adapter.quota):\n        return QUOTA",
        [
            "tests/test_quota_classification.py",
            "tests/test_quota_wiring.py",
            "tests/test_failures.py",
        ],
    ),
    (
        "classify: provider_error markers ignored",
        "src/afriend/failures.py",
        '    provider_error = outcome.provider_error or ""\n    return any(needle in provider_error for needle in markers.provider_error)',
        "    return False",
        ["tests/test_quota_classification.py", "tests/test_quota_wiring.py"],
    ),
    (
        "quota: a spent quota aborts the run like auth",
        "src/afriend/rounds.py",
        "            elif verdict == QUOTA:",
        "            elif verdict == QUOTA and False:",
        ["tests/test_quota_wiring.py"],
    ),
    (
        "models: tsv chatter no longer skipped",
        "src/afriend/models.py",
        '            if "\\t" not in line:\n                continue',
        "            if False:\n                continue",
        ["tests/test_models_listing.py"],
    ),
    (
        "models: ids with whitespace accepted",
        "src/afriend/models.py",
        "        if not candidate or any(char.isspace() for char in candidate):\n            continue",
        "        if not candidate:\n            continue",
        ["tests/test_models_listing.py"],
    ),
    (
        "models: empty listing reported as success",
        "src/afriend/models.py",
        '    if not models:\n        return ProviderModels(\n            adapter.name, supported=True, error="listing produced no recognizable model ids"\n        )',
        '    if False:\n        return ProviderModels(adapter.name, supported=True, error="unused")',
        ["tests/test_models_listing.py"],
    ),
    (
        "provider error only used when stderr is empty",
        "src/afriend/rounds.py",
        "    elif outcome.failure_reason is not None and provider_error:",
        "    elif outcome.failure_reason is not None and provider_error and not diagnostics:",
        ["tests/test_round_audit.py", "tests/test_provider_error.py", "tests/test_quota_wiring.py"],
    ),
]


# pytest's own exit codes. Only TESTS_FAILED means a mutation was noticed;
# every other non-zero code means pytest never got as far as judging it. The
# first version of this file treated any non-zero code as a kill, so an entry
# naming a test file that had been renamed away exited 4 (usage error, "file
# or directory not found") and was reported killed. One decision was
# certified as covered while nothing ran.
PYTEST_OK = 0
PYTEST_TESTS_FAILED = 1


def run(paths: list[str]) -> tuple[bool, str]:
    """Return (mutation was noticed, why not) for one mutated tree."""
    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "-x", "-p", "no:randomly", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        # The child must not cache bytecode. CPython validates a .pyc against
        # its source's (mtime, size), and these mutations are edits of equal
        # length restored within the same mtime-second -- so a .pyc compiled
        # from the mutated file stays "valid" for the restored one, and the
        # mutation goes on running out of __pycache__ with a clean source
        # tree. Found the hard way: three stdin-template tests failed against
        # a checkout that `git diff` reported as unmodified.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode == PYTEST_TESTS_FAILED:
        return True, ""
    if result.returncode == PYTEST_OK:
        return False, "tests passed against the mutation"
    tail = (result.stdout + result.stderr).strip().splitlines()
    detail = tail[-1] if tail else "no output"
    return False, f"pytest could not run (exit {result.returncode}): {detail}"


def missing_test_paths() -> list[str]:
    """Every test path named by a mutation, that does not exist.

    Checked before anything is mutated. A renamed test file is the failure
    this probe is least able to notice on its own, because the symptom --
    pytest exiting non-zero -- is indistinguishable from success unless the
    exit code is read.
    """
    referenced = {path for _label, _rel, _o, _m, tests in MUTATIONS for path in tests}
    return sorted(path for path in referenced if not (ROOT / path).is_file())


def purge_bytecode(path: pathlib.Path) -> None:
    """Drop any cached bytecode for a file that was just restored.

    Belt to the child's braces: PYTHONDONTWRITEBYTECODE stops this run from
    creating a poisoned .pyc, and this removes one an earlier run may already
    have left behind. Restoring the source is not enough on its own -- see
    `run()`.
    """
    for cached in path.parent.glob(f"__pycache__/{path.stem}.*.pyc"):
        cached.unlink(missing_ok=True)


def main() -> int:
    missing = missing_test_paths()
    if missing:
        print("error: mutations name test files that do not exist:", file=sys.stderr)
        print(*(f"  {path}" for path in missing), sep="\n", file=sys.stderr)
        return 2
    survived: list[tuple[str, str]] = []
    killed: list[str] = []
    broken: list[tuple[str, str]] = []
    for label, rel, original, mutated, tests in MUTATIONS:
        path = ROOT / rel
        text = path.read_text()
        if text.count(original) != 1:
            why = f"anchor matched {text.count(original)}x"
            broken.append((label, why))
            print(f"SKIP      {label} ({why})", flush=True)
            continue
        path.write_text(text.replace(original, mutated))
        try:
            noticed, why = run(tests)
        finally:
            path.write_text(text)
        # The probe edits real source files. Anything that leaves a mutation
        # on disk is worse than a failed check, so the restore is verified
        # rather than assumed.
        if path.read_text() != text:
            print(f"error: could not restore {rel} after mutating it", file=sys.stderr)
            return 2
        purge_bytecode(path)
        if noticed:
            killed.append(label)
            print(f"killed    {label}", flush=True)
        else:
            survived.append((label, why))
            print(f"SURVIVED  {label} ({why})", flush=True)
    print("\n--- summary ---")
    print(f"killed:   {len(killed)}")
    print(f"survived: {len(survived)}")
    print(f"skipped:  {len(broken)}")
    for label, why in survived:
        print(f"  SURVIVED: {label} ({why})")
    for label, why in broken:
        print(f"  SKIPPED:  {label} ({why})")
    # A survivor and a stale anchor are the same failure wearing different
    # clothes: a decision this file claims is covered, is not. Returning 0
    # for either made the whole probe unfalsifiable.
    return 1 if survived or broken else 0


if __name__ == "__main__":
    sys.exit(main())
