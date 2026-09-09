"""The probe gates the build, so the probe has to be able to fail.

Its first version could not. It returned 0 whatever happened, and it read
"pytest exited non-zero" as "the tests noticed the mutation" -- so an entry
naming a test file that had been renamed away exited 4 (usage error) and was
reported killed. One decision was certified as covered while nothing ran.
"""

import importlib.util
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]


def _probe():
    spec = importlib.util.spec_from_file_location("probe", REPO / "ci" / "mutation_probe.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["pytest"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_every_mutation_names_test_files_that_exist():
    """The rot this catches. Renaming a test file cannot be noticed by the
    probe's own result, because the symptom is a non-zero exit -- which is
    also what success looks like."""
    assert _probe().missing_test_paths() == []


def test_a_failing_test_is_the_only_thing_that_counts_as_a_kill(monkeypatch):
    module = _probe()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(1))

    assert module.run(["tests/whatever.py"]) == (True, "")


def test_a_pytest_that_could_not_run_is_not_a_kill(monkeypatch):
    """Exit 4 is "file or directory not found", exit 5 is "no tests
    collected". Neither is evidence about the mutation, and treating them as
    evidence is how a mutation gets certified by an empty run."""
    module = _probe()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _completed(4, stderr="ERROR: file or directory not found"),
    )

    noticed, why = module.run(["tests/gone.py"])

    assert noticed is False
    assert "could not run" in why and "exit 4" in why


def test_tests_passing_against_the_mutation_is_a_survivor(monkeypatch):
    module = _probe()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(0))

    noticed, why = module.run(["tests/whatever.py"])

    assert noticed is False
    assert "tests passed" in why


def test_the_child_is_forbidden_from_caching_bytecode(monkeypatch):
    """The subtlest failure this file has seen. CPython validates a `.pyc`
    against its source's (mtime, size); these mutations are equal-length
    edits restored inside the same mtime-second, so bytecode compiled from a
    mutated file stays valid for the restored one. The mutation then keeps
    running out of `__pycache__` against a source tree `git diff` calls
    clean -- and it did, breaking three unrelated tests.
    """
    module = _probe()
    captured: dict[str, object] = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return _completed(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    module.run(["tests/whatever.py"])

    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_restoring_a_file_also_drops_bytecode_an_earlier_run_left(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("x = 1\n")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    stale = cache / "module.cpython-313.pyc"
    stale.write_bytes(b"stale")
    unrelated = cache / "other.cpython-313.pyc"
    unrelated.write_bytes(b"keep")

    _probe().purge_bytecode(source)

    assert not stale.exists()
    assert unrelated.read_bytes() == b"keep"


def test_a_stale_anchor_fails_the_run_rather_than_being_skipped_quietly(monkeypatch):
    """A mutation whose anchor no longer matches is a decision this file
    claims to cover and does not. Reporting it as a skip and exiting 0 is the
    same lie as a survivor."""
    module = _probe()
    monkeypatch.setattr(
        module,
        "MUTATIONS",
        [("x", "src/afriend/envelopes.py", "NOT_IN_THE_FILE", "y", ["tests/test_adapters.py"])],
    )

    assert module.main() == 1


def test_a_mutation_naming_a_missing_test_file_refuses_before_mutating(monkeypatch, capsys):
    module = _probe()
    monkeypatch.setattr(
        module, "MUTATIONS", [("x", "src/afriend/envelopes.py", "a", "b", ["tests/test_gone.py"])]
    )
    before = (REPO / "src" / "afriend" / "envelopes.py").read_bytes()

    assert module.main() == 2
    assert "tests/test_gone.py" in capsys.readouterr().err
    assert (REPO / "src" / "afriend" / "envelopes.py").read_bytes() == before


@pytest.mark.parametrize("mutation", _probe().MUTATIONS, ids=lambda entry: entry[0])
def test_every_mutation_anchor_matches_its_file_exactly_once(mutation):
    """A mutation is only meaningful if it can still be applied. Asserted
    here as well as at run time so a drifted anchor names the entry in a
    two-second test, rather than surfacing as a skip several minutes into a
    probe run."""
    label, rel, original, mutated, _tests = mutation
    text = (REPO / rel).read_text()

    assert text.count(original) == 1, f"{label}: anchor matched {text.count(original)}x"
    assert original != mutated, label
