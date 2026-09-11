"""The diagram gate's own failure modes.

`ci/verify_diagrams_render.sh` had no test of its own, so the one thing it
asserts -- that a silently broken render is caught -- was never exercised.
Both checks below fail against the pre-fix script.
"""

from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "ci" / "verify_diagrams_render.sh"

# Comfortably past the 64KiB pipe buffer, which is what decided whether the
# old `sed | grep -q` form saw the match or lost it to SIGPIPE.
OVERSIZED = 300_000


def _error_svg(size: int) -> str:
    """An SVG shaped like PlantUML's error image: the banner first, then
    enough markup that a reader of the stream exits long before the writer
    finishes."""
    return '<?xml version="1.0"?><svg><text>Syntax Error?</text>' + ("x" * size) + "</svg>"


@pytest.mark.parametrize("size", [1_000, OVERSIZED])
def test_the_error_image_check_survives_its_own_pipeline(tmp_path, size):
    """A `grep -q` that matches exits at once; under `set -o pipefail` the
    writer upstream then takes SIGPIPE and the pipeline reports 141, which
    an `if` reads as "no match". The gate printed "render cleanly" and
    exited 0 for exactly the input it exists to reject -- but only once the
    writer outran the pipe buffer, so it failed by file size and would have
    started passing silently as these diagrams grew. The largest real SVG
    here is already about 64KiB.
    """
    svg = tmp_path / "d.svg"
    svg.write_text(_error_svg(size), encoding="utf-8")

    script = (
        "set -euo pipefail\n"
        f'if grep -qiE "Syntax Error|Cannot find group|syntax is deprecated" '
        f"< <(sed 's/&#160;/ /g' {svg!s}); then echo CAUGHT; else echo MISSED; fi\n"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert out.stdout.strip() == "CAUGHT", (size, out.stdout, out.stderr)


def test_the_gate_uses_no_pipe_into_a_quiet_grep():
    """Pin the shape, not just one instance of it.

    Any `... | grep -q` in this script is the same latent false pass, and
    the next one would be added in good faith by someone matching the
    surrounding style.
    """
    text = GATE.read_text(encoding="utf-8")
    # Join backslash continuations first: the real invocations span lines,
    # and the `|` characters inside a grep's own alternation are not pipes.
    joined = re.sub(r"\\\n\s*", " ", text)
    offenders = [
        line.strip()
        for line in joined.splitlines()
        if not line.lstrip().startswith("#") and re.search(r"(?<!\|)\|(?!\|)\s*grep\s+-\w*q", line)
    ]
    assert offenders == [], offenders


@pytest.mark.skipif(shutil.which("plantuml") is None, reason="plantuml not installed")
def test_the_gate_passes_on_the_committed_sources():
    """The success path, so a gate that refuses everything is not mistaken
    for a gate that verifies something."""
    out = subprocess.run([str(GATE)], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "render cleanly" in out.stdout
