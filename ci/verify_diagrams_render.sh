#!/usr/bin/env bash
# Fail if any architecture diagram cannot be rendered, or if a committed
# render is itself a PlantUML error image.
#
# `make diagrams` is not run by anything automatic, and for several days two
# diagrams could not be rendered at all: `run-flow.puml` and
# `gate-workflow.puml` both died with "Cannot find group" on every PlantUML
# from 1.2020.02 to 1.2026.0. The committed PNGs were therefore impossible to
# reproduce from the committed sources, and nothing said so -- the digest
# manifest only proves the PNG matches the .puml it was recorded against, not
# that the .puml still renders.
#
# Renderability, not byte equality: PlantUML changes its own layout between
# releases, so comparing bytes would pin the repository to one build of a tool
# nobody installs the same way twice. This catches the defect that actually
# happened -- a source no version will parse -- on whatever version is to hand.
set -euo pipefail

cd "$(dirname "$0")/.."
sources=(docs/architecture/*.puml)

if ! command -v plantuml >/dev/null 2>&1; then
  # A skip looks exactly like a pass, so it is only allowed off CI.
  if [ -n "${CI:-}" ]; then
    echo "ERROR: plantuml is not installed, so the diagram sources went unchecked." >&2
    exit 1
  fi
  echo "SKIP: plantuml not installed; run 'make diagrams-check' after installing it." >&2
  exit 0
fi

# Render into a throwaway directory: this check must never touch the committed
# PNG/SVG pair, which is regenerated deliberately by `make diagrams`.
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

status=0
output=$(plantuml -tsvg -o "$out" "${sources[@]}" 2>&1) || status=$?
if [ -n "$output" ]; then
  echo "$output"
fi
# Key the failure off PlantUML's own markers, not the substring "error": the
# JVM writes unrelated `Fontconfig error:` lines to stderr on a box with no
# writable font cache while rendering every diagram correctly.
if [ "$status" -ne 0 ] || echo "$output" | grep -qE \
    "Some diagram description contains errors|Error line |Cannot find group|Warning: no image"; then
  echo "ERROR: at least one diagram source failed to render (see above)." >&2
  echo "Run 'make diagrams' locally to reproduce." >&2
  exit 1
fi

# PlantUML exits 0 when a source produces no diagram at all (no @startuml, an
# empty file), so "it rendered" has to be counted from the output directory --
# never from the length of the source list, which is known before running.
rendered=$(find "$out" -name '*.svg' -type f | wc -l)
if [ "$rendered" -ne "${#sources[@]}" ]; then
  echo "ERROR: ${#sources[@]} diagram sources produced only $rendered renders." >&2
  echo "A source that renders nothing is exactly what this gate exists to catch." >&2
  exit 1
fi

# A render can also FAIL SILENTLY: PlantUML writes an error image, or a banner
# across the top of an otherwise fine diagram, and still exits 0. Check the
# FRESH renders -- the committed pair is checked by pytest, and is clean by
# construction here because `make diagrams` is what last wrote it.
#
# PlantUML emits every space inside <text> as `&#160;`, so a phrase typed with
# ordinary spaces cannot match the raw markup. Normalize before grepping.
for svg in "$out"/*.svg; do
  if sed 's/&#160;/ /g' "$svg" | grep -qiE "Syntax Error|Cannot find group|syntax is deprecated"; then
    echo "ERROR: $(basename "$svg" .svg) renders as a PlantUML error image, not a diagram." >&2
    sed 's/&#160;/ /g' "$svg" | grep -oiE "Syntax Error|Cannot find group|syntax is deprecated" | head -3 >&2
    exit 1
  fi
done

echo "all ${#sources[@]} diagram sources render cleanly."
