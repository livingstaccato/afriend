"""The diagram gate's own failure modes, and the ones no gate can see.

`ci/verify_diagrams_render.sh` had no test of its own, so the one thing it
asserts -- that a silently broken render is caught -- was never exercised.
The first two checks fail against the pre-fix script.

The source checks after them guard what rendering cannot. One names a
colour syntax that renders on PlantUML 1.2026.6 and fails on 1.2026.7, so
it depends on which release is installed; the other two name styling
mistakes that render perfectly and wrong, and would never fail anything.
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


DIAGRAMS = sorted((REPO / "docs" / "architecture").glob("*.puml"))

# `#RRGGBB:label;` -- the inline activity colour. A legend swatch is written
# `|<#RRGGBB> |`, a table cell rather than an activity, so anchoring on the
# `#` at the start of the line keeps the two apart.
INLINE_COLOUR = re.compile(r"^\s*#[0-9A-Fa-f]{6}\s*:")


@pytest.mark.parametrize("source", DIAGRAMS, ids=lambda p: p.stem)
def test_no_activity_carries_an_inline_colour_prefix(source):
    """PlantUML 1.2026.7 stopped rendering this form inside a group.

    A coloured activity in or beside a `partition` or `repeat` fails the
    whole source with "Cannot find group", reported against the line that
    closes the group rather than the coloured one. `ci/install_plantuml.sh`
    pins a release that rejects it, so the render gate would now catch a
    reintroduction -- but only where plantuml is installed, and that gate
    skips silently when it is not. This says so without rendering anything.
    """
    offenders = [
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if INLINE_COLOUR.match(line)
    ]
    assert offenders == [], offenders


@pytest.mark.parametrize("source", DIAGRAMS, ids=lambda p: p.stem)
def test_every_style_class_declares_one_property_per_line(source):
    """The silent half, which no renderer can catch for us.

    `.downgrade { BackgroundColor #A  LineColor #B }` is read as one
    malformed value: PlantUML drops the whole class without a word, the
    tagged activities render unstyled, and the diagram still reports
    success. Every semantic fill in these sources depends on that not
    happening, and nothing downstream would notice if it did.
    """
    text = source.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in text.splitlines()
        # A class opened and closed on one line, carrying two properties.
        if re.match(r"^\s*\.\w+\s*\{.*\}", line)
        and len(re.findall(r"[A-Za-z]+\s+#[0-9A-Fa-f]{6}", line)) > 1
    ]
    assert offenders == [], offenders


@pytest.mark.parametrize("source", DIAGRAMS, ids=lambda p: p.stem)
def test_every_stereotype_used_is_a_class_the_source_defines(source):
    """A misspelt `<<class>>` is not an error either -- it renders plain.

    The node keeps its default fill and the diagram succeeds, so a typo
    costs exactly the meaning the colour was carrying.
    """
    text = source.read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*\.(\w+)\s*\{", text, re.MULTILINE))
    used = set(re.findall(r"<<(\w+)>>", text))
    assert used <= defined, sorted(used - defined)


@pytest.mark.skipif(shutil.which("plantuml") is None, reason="plantuml not installed")
def test_the_gate_passes_on_the_committed_sources():
    """The success path, so a gate that refuses everything is not mistaken
    for a gate that verifies something."""
    out = subprocess.run([str(GATE)], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "render cleanly" in out.stdout
