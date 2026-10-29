"""Require complete successful push-to-main CI for the exact release commit."""

import argparse
from collections import defaultdict
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REQUIRED_STEPS = {
    "quality (3.11)": ("pytest", "assert containment tests ran"),
    "quality (3.12)": ("pytest", "assert containment tests ran"),
    "quality (3.13)": ("pytest", "mutation-probe", "assert containment tests ran"),
    "windows": ("pytest",),
    "Windows startup (claude)": (
        "Install real reviewer CLI",
        "Exercise native startup and expected rejection",
    ),
    "Windows startup (codex)": (
        "Install real reviewer CLI",
        "Exercise native startup and expected rejection",
    ),
    "Windows startup (opencode)": (
        "Install real reviewer CLI",
        "Exercise native startup and expected rejection",
    ),
    "Windows startup (pi)": (
        "Install real reviewer CLI",
        "Exercise native startup and expected rejection",
    ),
}


def select_successful_run(runs: list[dict[str, Any]], sha: str, workflow_id: int) -> dict[str, Any]:
    matching = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("workflow_id") == workflow_id
        and run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
    ]
    if not matching or any(type(run.get("id")) is not int for run in matching):
        raise RuntimeError("no valid push-to-main CI run for the exact tagged commit")
    run = max(matching, key=lambda item: item["id"])
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise RuntimeError(f"latest matching CI run {run['id']} is not completed successfully")
    return run


def require_successful_jobs(jobs: list[dict[str, Any]], sha: str, run_id: int) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[int] = set()
    for job in jobs:
        if (
            not isinstance(job, dict)
            or job.get("run_id") != run_id
            or job.get("head_sha") != sha
            or not isinstance(job.get("name"), str)
            or type(job.get("id")) is not int
            or type(job.get("run_attempt")) is not int
            or job["run_attempt"] < 1
            or job["id"] in seen_ids
        ):
            raise RuntimeError("CI job evidence has missing, duplicate or mismatched identity")
        seen_ids.add(job["id"])
        grouped[job["name"]].append(job)
    missing = set(REQUIRED_STEPS) - grouped.keys()
    if missing:
        raise RuntimeError(f"required CI jobs missing: {sorted(missing)}")
    for name, attempts in grouped.items():
        latest_attempt = max(job["run_attempt"] for job in attempts)
        latest = [job for job in attempts if job["run_attempt"] == latest_attempt]
        if len(latest) != 1:
            raise RuntimeError(f"ambiguous duplicate CI job: {name}")
        job = latest[0]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise RuntimeError(f"CI job did not pass: {name}")
        steps = job.get("steps")
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise RuntimeError(f"CI job has malformed step evidence: {name}")
        for required in REQUIRED_STEPS.get(name, ()):
            matched = [step for step in steps if step.get("name") == required]
            if (
                len(matched) != 1
                or matched[0].get("status") != "completed"
                or matched[0].get("conclusion") != "success"
            ):
                raise RuntimeError(f"required CI step did not pass: {name}: {required}")


class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token

    def get(self, path: str) -> dict[str, Any]:
        request = Request(
            "https://api.github.com/" + path,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                data = json.load(response)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"cannot verify GitHub CI evidence: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("GitHub CI response is not an object")
        return data

    def collection(self, path: str, key: str, **query: str) -> list[dict[str, Any]]:
        result = []
        for page in range(1, 11):
            data = self.get(path + "?" + urlencode({**query, "per_page": 100, "page": page}))
            rows = data.get(key)
            if not isinstance(rows, list):
                raise RuntimeError(f"GitHub response lacks {key} records")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise RuntimeError("too many CI records to verify safely; inspect the run history")


def verify(repository: str, sha: str, client: GitHub) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or ".." in repository:
        raise RuntimeError("invalid GitHub repository")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("release SHA must be the full lowercase commit hash")
    root = f"repos/{repository}/actions"
    workflow = client.get(root + "/workflows/ci.yml")
    if (
        workflow.get("path") != ".github/workflows/ci.yml"
        or workflow.get("state") != "active"
        or type(workflow.get("id")) is not int
    ):
        raise RuntimeError("expected CI workflow is missing, inactive or malformed")
    runs = client.collection(
        root + f"/workflows/{workflow['id']}/runs",
        "workflow_runs",
        head_sha=sha,
        event="push",
        branch="main",
    )
    run = select_successful_run(runs, sha, workflow["id"])
    jobs = client.collection(root + f"/runs/{run['id']}/jobs", "jobs", filter="all")
    require_successful_jobs(jobs, sha, run["id"])
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    try:
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise RuntimeError("GH_TOKEN with actions:read is required to verify CI")
        run = verify(args.repository, args.sha, GitHub(token))
    except RuntimeError as exc:
        print(f"Release CI check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified exact-commit main CI run {run['id']} for {args.sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
