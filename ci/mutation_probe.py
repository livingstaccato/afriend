"""Targeted mutation probe for the provider transport and failure paths.

Not a general mutation runner: a fixed list of plausible wrong versions of
decisions this code makes, each paired with the tests that ought to notice.
A survivor means no test asserts that decision -- which is the only thing
a passing suite cannot tell you about itself.

Run with `make mutation-probe`. Four of these twelve survived the first
time, including the ordering between an exhausted quota and a broken
credential, and the one case that motivated the whole change: a real codex
failure carries BOTH a noisy stderr and a structured error, and every test
supplied only one of them.
"""

from __future__ import annotations

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
        "terminal event: any final line ends the stream",
        "src/afriend/envelopes.py",
        "        return isinstance(parsed, dict) and (\n            parsed.get(envelope.match_field) == envelope.terminal_event\n        )",
        "        return isinstance(parsed, dict)",
        ["tests/test_envelopes.py", "tests/test_envelope_fixtures.py", "tests/test_spawn.py"],
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


def run(paths: list[str]) -> bool:
    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "-x", "-p", "no:randomly", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    survived, killed, broken = [], [], []
    for label, rel, original, mutated, tests in MUTATIONS:
        path = ROOT / rel
        text = path.read_text()
        if text.count(original) != 1:
            broken.append((label, f"anchor matched {text.count(original)}x"))
            print(f"SKIP  {label} (anchor matched {text.count(original)}x)", flush=True)
            continue
        path.write_text(text.replace(original, mutated))
        try:
            passed = run(tests)
        finally:
            path.write_text(text)
        if passed:
            survived.append(label)
            print(f"SURVIVED  {label}", flush=True)
        else:
            killed.append(label)
            print(f"killed    {label}", flush=True)
    print("\n--- summary ---")
    print(f"killed:   {len(killed)}")
    print(f"survived: {len(survived)}")
    print(f"skipped:  {len(broken)}")
    for label in survived:
        print(f"  SURVIVED: {label}")
    for label, why in broken:
        print(f"  SKIPPED:  {label} ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
