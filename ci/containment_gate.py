"""Fail CI unless each named OS-containment test actually passes all phases.

Loaded explicitly by assert_sandbox_tested.sh, never by the ordinary suite.
Passing profile-construction or mocked dispatch tests cannot supply this evidence.
"""

from collections import defaultdict

import pytest

REQUIRED_NODEIDS = (
    "tests/test_sandbox.py::test_a_file_inside_the_workdir_is_readable",
    "tests/test_sandbox.py::test_a_file_outside_the_workdir_is_not_readable",
    "tests/test_sandbox_findings.py::test_a_confined_process_really_cannot_see_withheld_secrets",
    "tests/test_scratch_placement.py::test_the_reviewed_worktree_is_left_clean",
    "tests/test_containment_readonly.py::test_a_readonly_worktree_allows_reads_and_denies_writes",
)


class _ContainmentEvidence:
    def __init__(self) -> None:
        self.reports: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.nodeid in REQUIRED_NODEIDS:
            self.reports[report.nodeid].append(
                (report.when, report.outcome, hasattr(report, "wasxfail"))
            )

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        required = [
            ("setup", "passed", False),
            ("call", "passed", False),
            ("teardown", "passed", False),
        ]
        missing = [node for node in REQUIRED_NODEIDS if self.reports[node] != required]
        if missing:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            terminal = session.config.pluginmanager.get_plugin("terminalreporter")
            if terminal is not None:
                terminal.write_sep(
                    "=", "ERROR: required containment evidence missing or not passed"
                )
                for node in missing:
                    terminal.write_line(f"{node}: {self.reports[node] or 'not executed'}")


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(_ContainmentEvidence(), "containment-evidence")
