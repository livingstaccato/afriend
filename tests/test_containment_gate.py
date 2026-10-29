"""The CI gate must reject real pytest runs that omit containment evidence."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _environment():
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(_ROOT), env.get("PYTHONPATH", "")))
    return env


@pytest.mark.posix_only(reason="CI containment entrypoint is a shell script")
@pytest.mark.parametrize("mode", ["deselected", "skipped"])
def test_shell_gate_rejects_successful_pytest_without_containment(tmp_path, mode):
    env = _environment()
    if mode == "deselected":
        env["PYTEST_ADDOPTS"] = "-k missing_system_path"
    else:
        plugin = tmp_path / "omit_containment.py"
        plugin.write_text(
            "import pytest\n"
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            "        item.add_marker(pytest.mark.skip(reason='maintenance'))\n"
        )
        env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), env["PYTHONPATH"]))
        env["PYTEST_PLUGINS"] = "omit_containment"
    result = subprocess.run(
        ["bash", "ci/assert_sandbox_tested.sh"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "containment tests ran." not in result.stdout


@pytest.mark.parametrize(
    "outcome",
    [
        "passed",
        "missing",
        "deselected",
        "skipped",
        "failed",
        "setup_error",
        "teardown_error",
        "xfail",
        "xpass",
    ],
)
def test_plugin_requires_complete_pass_reports_for_each_named_node(tmp_path, outcome):
    """Fixture cases test report validation, not the OS containment claim itself."""
    cases = {
        "test_sandbox.py": [
            "test_a_file_inside_the_workdir_is_readable",
            "test_a_file_outside_the_workdir_is_not_readable",
        ],
        "test_sandbox_findings.py": ["test_a_confined_process_really_cannot_see_withheld_secrets"],
        "test_scratch_placement.py": ["test_the_reviewed_worktree_is_left_clean"],
        "test_containment_readonly.py": ["test_a_readonly_worktree_allows_reads_and_denies_writes"],
    }
    directory = tmp_path / "tests"
    directory.mkdir()
    for filename, names in cases.items():
        definitions = ["import pytest\n"]
        for name in names:
            body = "    pass\n"
            prefix = ""
            if name == "test_a_file_inside_the_workdir_is_readable":
                if outcome == "missing":
                    continue
                if outcome == "skipped":
                    body = "    pytest.skip('maintenance')\n"
                elif outcome == "failed":
                    body = "    assert False\n"
                elif outcome in {"setup_error", "teardown_error"}:
                    prefix = (
                        "@pytest.fixture\ndef broken():\n"
                        + ("    yield\n" if outcome == "teardown_error" else "")
                        + "    raise RuntimeError('broken fixture')\n\n"
                        + "@pytest.mark.usefixtures('broken')\n"
                    )
                elif outcome in {"xfail", "xpass"}:
                    prefix = "@pytest.mark.xfail(reason='not proof')\n"
                    if outcome == "xfail":
                        body = "    assert False\n"
            definitions.append(f"{prefix}def {name}():\n{body}")
        (directory / filename).write_text("\n".join(definitions))
    # Many unrelated passing tests must never replace a missing required node.
    (directory / "test_unrelated.py").write_text("def test_unrelated():\n    pass\n")
    env = _environment()
    if outcome == "deselected":
        env["PYTEST_ADDOPTS"] = "-k not test_a_file_inside_the_workdir_is_readable"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci.containment_gate", "tests", "-q"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if outcome == "passed":
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        assert "required containment evidence missing or not passed" in result.stdout
