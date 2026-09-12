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

# `#RRGGBB:label;` -- the inline activity colour. PlantUML accepts a colour
# NAME and three-digit hex in the same position, so six hex digits is the
# narrowest possible spelling and the least likely to be typed by hand:
# `#LightYellow:label;` breaks a group exactly as `#FFE0B2:label;` does. A
# legend swatch is written `|<#RRGGBB> |`, a table cell rather than an
# activity, so anchoring on the `#` at the start of the line keeps the two
# apart; a skinparam carries its colour mid-line and is not matched either.
INLINE_COLOUR = re.compile(r"^\s*#[0-9A-Za-z]{3,}\s*:")

# `BackgroundColor #F6E7C8` -- one styling property and its value.
STYLE_PROPERTY = re.compile(r"[A-Za-z]+\s+#[0-9A-Za-z]{3,}")


def _style_class_body_lines(text: str) -> list[str]:
    """Every line inside a `<style>` class body, brace depth tracked.

    Line-by-line matching on `.name { ... }` only ever sees a class opened
    and closed on one line, which is a form none of these sources use.
    """
    inside = False
    depth = 0
    body: list[str] = []
    for line in text.splitlines():
        opens = line.count("{")
        closes = line.count("}")
        if not inside and re.match(r"^\s*\.\w+\s*\{", line):
            inside = True
            depth = 0
        if inside:
            body.append(line)
            depth += opens - closes
            if depth <= 0 and closes:
                inside = False
    return body


@pytest.mark.parametrize("source", DIAGRAMS, ids=lambda p: p.stem)
def test_no_activity_carries_an_inline_colour_prefix(source):
    """PlantUML 1.2026.7 stopped rendering this form in certain positions.

    A coloured activity directly before an `if` -- with or without a group --
    at a group boundary, or ending an `if` branch whose `else` is empty or
    absent inside a group fails the whole source, as "Cannot find group",
    "Cannot find if", "Cannot find repeat" or "Syntax Error?", and often
    against a later line than the coloured one. `ci/install_plantuml.sh`
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

    The first version of this test matched `^\\s*\\.\\w+\\s*\\{.*\\}`, which
    requires the class to open and close on one line. Every class here spans
    four, so the realistic mistake -- reflowing two properties onto an
    interior line, which begins with `BackgroundColor` -- was never looked
    at, and the test passed by construction on the shape the sources have.
    """
    offenders = [
        line.strip()
        for line in _style_class_body_lines(source.read_text(encoding="utf-8"))
        if len(STYLE_PROPERTY.findall(line)) > 1
    ]
    assert offenders == [], offenders


@pytest.mark.parametrize("source", DIAGRAMS, ids=lambda p: p.stem)
def test_every_stereotype_used_is_a_class_the_source_defines(source):
    """A misspelt `<<class>>` is not an error either -- it renders plain.

    The node keeps its default fill and the diagram succeeds, so a typo
    costs exactly the meaning the colour was carrying.

    The pattern deliberately accepts anything between the angle brackets
    rather than `\\w+`. `<<#FFE0B2>>` is this repository's ORIGINAL colour
    syntax, abandoned because it fails inside a nested `if` on every release
    tried; spelled `\\w+`, a reintroduced one would not even be looked at,
    because `#` is not a word character.
    """
    text = source.read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*\.(\w+)\s*\{", text, re.MULTILINE))
    used = set(re.findall(r"<<([^>]+)>>", text))
    assert used <= defined, sorted(used - defined)


STYLED = [source for source in DIAGRAMS if "<style>" in source.read_text(encoding="utf-8")]


def test_some_source_actually_declares_style_classes():
    """Guard the parametrization below.

    If `STYLED` ever empties -- the classes removed, the block renamed --
    the fill check would collect no cases and disappear from the run
    without failing anything.
    """
    assert STYLED, "no diagram declares <style> classes, so the fill check covers nothing"


@pytest.mark.parametrize("source", STYLED, ids=lambda p: p.stem)
def test_every_used_class_fill_reaches_the_committed_render(source):
    """The one check that holds however the class was broken.

    A dropped class is invisible to everything else here: PlantUML renders
    the node in the default fill and exits 0, `make diagrams` rewrites the
    PNG and SVG, `scripts/write_diagram_manifest.py` rewrites the digests to
    match what it just wrote, and the render gate sees a clean diagram. Every
    gate stays green while the semantic colour -- the whole point of the
    class -- is gone. Asserting the declared fill is present in the render is
    what separates correct output from silently degraded output, and it does
    not care which malformation caused it.
    """
    text = source.read_text(encoding="utf-8")
    fills = dict(
        re.findall(r"\.(\w+)\s*\{[^}]*?BackgroundColor\s+(#[0-9A-Za-z]{3,})", text, re.DOTALL)
    )
    used = set(re.findall(r"<<(\w+)>>", text))
    rendered = source.with_suffix(".svg").read_text(encoding="utf-8").lower()

    missing = sorted(
        name for name in used if name not in fills or fills[name].lower() not in rendered
    )
    assert missing == [], missing


INSTALLER = REPO / "ci" / "install_plantuml.sh"

# The release that stopped parsing the inline colour form. Pinned below this,
# the render gate happily accepts what
# `test_no_activity_carries_an_inline_colour_prefix` exists to reject, and the
# two halves of that guard quietly stop agreeing.
FIRST_STRICT_PLANTUML = (1, 2026, 7)


def test_the_pinned_plantuml_is_one_that_rejects_the_inline_colour_form():
    """The coupling was prose in a docstring, true of nothing.

    Someone pinning an older release to sidestep an unrelated layout change
    would re-arm the exact defect this gate was built for, with every check
    still green.
    """
    declared = re.search(r"^VERSION=(\S+)", INSTALLER.read_text(encoding="utf-8"), re.MULTILINE)
    assert declared, "ci/install_plantuml.sh declares no VERSION"

    pinned = tuple(int(part) for part in declared.group(1).split("."))
    assert pinned >= FIRST_STRICT_PLANTUML, (pinned, FIRST_STRICT_PLANTUML)


@pytest.mark.skipif(shutil.which("plantuml") is None, reason="plantuml not installed")
@pytest.mark.external
def test_the_gate_passes_on_the_committed_sources():
    """The success path, so a gate that refuses everything is not mistaken
    for a gate that verifies something."""
    out = subprocess.run([str(GATE)], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "render cleanly" in out.stdout
