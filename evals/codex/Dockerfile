# The only place the Codex activation eval runs Codex: an image holding Codex
# and no other model CLI, so a prompt that goes looking for `afriend`, `agy`,
# `claude` or `opencode` finds nothing to run. Built and run by
# scripts/run_codex_skill_eval.py, which passes CODEX_VERSION.
#
# Pinned by digest: a moving tag would change what the eval runs in without a
# commit saying so.
FROM node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

# Codex verifies TLS against the system certificate bundle, which the slim base
# leaves out. Node carries its own, so `npm install` succeeding proves nothing:
# without this, every login and every run fails with "error sending request".
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG CODEX_VERSION
RUN test -n "$CODEX_VERSION" \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force

RUN useradd --create-home --uid 10001 evaluser
USER evaluser
# Created as evaluser, so the login volume mounted here is writable by it.
RUN mkdir -p /home/evaluser/.codex
WORKDIR /home/evaluser
