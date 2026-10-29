"""Execute the readonly worktree policy against an actual OS sandbox."""

from dataclasses import replace
import shutil
import subprocess

import pytest

from afriend import sandbox


@pytest.mark.sandbox
def test_a_readonly_worktree_allows_reads_and_denies_writes(tmp_path):
    mechanism = sandbox.detect()
    if mechanism is None:
        pytest.skip("no OS sandbox mechanism on this machine")
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifact = workdir / "artifact.md"
    artifact.write_text("REVIEW INPUT\n")
    policy = sandbox.policy_for(workdir, "sh", ())
    # Match the outer readonly workdir policy used by opted-in adapters.
    policy = replace(policy, workdir_writable=False)
    argv = sandbox.wrap(
        [
            shutil.which("sh") or "/bin/sh",
            "-c",
            'cat "$1"; printf MODIFIED > "$1"',
            "sh",
            str(artifact),
        ],
        mechanism,
        policy,
        tmp_path / "profile.sb",
    )
    result = subprocess.run(argv, capture_output=True, text=True, cwd=workdir, timeout=15)
    assert result.stdout == "REVIEW INPUT\n", result.stderr
    assert result.returncode != 0, "sandbox permitted a write to the readonly worktree"
    assert artifact.read_text() == "REVIEW INPUT\n"
