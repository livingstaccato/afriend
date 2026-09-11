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
if [ "$status" -ne 0 ] || echo "$output" | grep -qiE "error|cannot find"; then
  echo "ERROR: at least one diagram source failed to render (see above)." >&2
  echo "Run 'make diagrams' locally to reproduce." >&2
  exit 1
fi

# A render can also FAIL SILENTLY into a committed file: PlantUML writes an
# error image and still exits, so the repository can hold a green-on-black
# stack dump that looks like a diagram to every other check.
for committed in docs/architecture/*.svg; do
  if grep -qiE "Cannot find group|Syntax Error" "$committed"; then
    echo "ERROR: $committed is a PlantUML error image, not a diagram." >&2
    exit 1
  fi
done

echo "all ${#sources[@]} diagram sources render, and no committed render is an error image."
