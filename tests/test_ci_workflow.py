"""CI must fail a hung run in minutes, and say where it hung.

The Windows job's pytest step once sat for over half an hour past its last
progress line under GitHub's six-hour default, printing nothing that named a
test.
"""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    names = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\n", body, re.MULTILINE))
    return {
        match.group(1): body[match.end() : following.start() if following else len(body)]
        for match, following in zip(names, [*names[1:], None], strict=True)
    }


def _job_timeout_minutes(job: str) -> int | None:
    found = re.search(r"^    timeout-minutes: (\d+)$", job, re.MULTILINE)
    return int(found.group(1)) if found else None


def test_every_ci_job_has_a_timeout():
    jobs = _jobs()
    assert {"quality", "windows"} <= set(jobs)
    missing = sorted(name for name, job in jobs.items() if _job_timeout_minutes(job) is None)
    assert missing == []


def test_a_hung_test_dumps_every_thread_before_the_job_is_killed():
    options = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    seconds = options["tool"]["pytest"]["ini_options"]["faulthandler_timeout"]
    shortest_job = min(_job_timeout_minutes(job) or 0 for job in _jobs().values())
    assert 0 < seconds < shortest_job * 60


def test_the_windows_job_names_each_test_as_it_finishes():
    """A killed job never prints pytest's failure summary, and quiet progress
    dots name nothing: the only record of which tests failed is a line per
    test, written as each one finishes. pyproject's addopts already pass -q,
    which a single -v only cancels -- the first attempt still printed dots."""
    windows = _jobs()["windows"]
    assert re.search(r"^\s+run: uv run pytest -n 4 -vv$", windows, re.MULTILINE)
