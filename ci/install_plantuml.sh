#!/usr/bin/env bash
# Install the PlantUML release these diagram sources are authored against.
#
# Ubuntu ships 1.2020.02, six years behind what a developer gets from brew or
# any current distribution, and the two parsers disagree about how an activity
# may be coloured. The `<style>` class form the sources use renders on 1.2026.x
# and fails on 1.2020.02; the inline `#RRGGBB:label;` form it replaced does the
# reverse. From 1.2026.7 it fails a source whose coloured activity sits
# directly before an `if` (group or no group), at a group boundary, or at the
# end of an `if` branch whose `else` is empty or absent inside a group -- as
# "Cannot find group", "Cannot find if", "Cannot find repeat" or "Syntax
# Error?".
# No colour syntax satisfies both, so a gate running the parser nobody develops
# against passes sources nobody can render -- which is the defect the diagram
# gate exists to catch.
#
# Pinned by version AND digest. An unpinned "latest" would change the parser
# under the gate without a commit, which is exactly how 1.2026.8 broke these
# sources: they were rendered and committed on one release and became
# unrenderable on the next, with nothing in the repository saying so.
set -euo pipefail

VERSION=1.2026.8
SHA256=5e1ecfa8ecd32c90b03bbf3b1eb6f020943f98ab0fcf4032be31a0002ee2c462
RELEASE_URL="https://github.com/plantuml/plantuml/releases/download/v${VERSION}/plantuml-${VERSION}.jar"
JAR=/usr/local/lib/plantuml.jar

# `apt-get update` first: the runner image's package lists go stale as the
# Ubuntu archive rotates, and act's container image ships with them cleared
# entirely, so the install is otherwise a coin flip on CI and a hard "Unable
# to locate package" under `make act-ci`.
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends default-jre-headless graphviz

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

curl -fsSL -o "$scratch/plantuml.jar" "$RELEASE_URL"
# Verify before installing, not after: a jar that fails this check must never
# reach a path the gate would then run.
echo "${SHA256}  ${scratch}/plantuml.jar" | sha256sum -c -

sudo install -D -m 0644 "$scratch/plantuml.jar" "$JAR"

# The Makefile and ci/verify_diagrams_render.sh both invoke `plantuml` by
# name, so the jar needs a launcher on PATH rather than a documented
# `java -jar` incantation nobody would remember to use.
printf '#!/bin/sh\nexec java -Djava.awt.headless=true -jar %s "$@"\n' "$JAR" \
    | sudo tee /usr/local/bin/plantuml >/dev/null
sudo chmod 0755 /usr/local/bin/plantuml

# Prove the launcher works and reports the pinned version, so a silently
# broken install cannot look like a successful one.
#
# Compare the extracted version token for equality rather than asking whether
# the banner CONTAINS the pinned string: as a substring, a pin of 1.2026.8 is
# satisfied by 1.2026.80, and the check that exists to catch the wrong release
# would wave through a different one.
installed="$(plantuml -version | head -1)"
echo "$installed"
reported="$(printf '%s\n' "$installed" | sed -n 's/.*[Vv]ersion \([0-9][0-9.]*\).*/\1/p')"
if [ "$reported" != "$VERSION" ]; then
    echo "ERROR: expected PlantUML $VERSION, got: ${reported:-no version in \"$installed\"}" >&2
    exit 1
fi
