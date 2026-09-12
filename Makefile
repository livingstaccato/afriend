.PHONY: help install lint type-check test test-fast plugin-sync mutation-probe version-sync max-loc wheel-assets wheel-install release-distributions diagrams plugin-sync-copy diagrams-check quality check act-dry act-ci \
	eval-claude eval-codex-build eval-codex-login eval-codex eval-friends eval-friends-score

# Live evals (`make eval-*`) make real model calls on your own logins, so they
# are manual only: none is a prerequisite of `quality`, and CI runs none.
EVAL_RUNS ?= 2
# Outside any git repository: inside this checkout, friends would get
# repository scope and could read the spec revision that holds the answers.
FRIEND_EVAL_DIR ?= $(or $(TMPDIR),/tmp)/afriend-friend-eval
# The run to score: `afriend run --out` holding exactly one run, or one run dir.
FRIEND_EVAL_RUN ?= $(FRIEND_EVAL_DIR)/runs
# 1 LLM judge, 2 hand mapping, 3 keyword heuristic; 1 and 2 need FRIEND_EVAL_MAPPING.
FRIEND_EVAL_METHOD ?= 3
FRIEND_EVAL_MAPPING ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync --all-extras

lint: ## Run ruff format + lint
	uv run ruff format --check .
	uv run ruff check .

type-check: ## Run mypy strict
	uv run mypy src

test: ## Run the test suite
	uv run pytest -n 4

test-fast: ## Run the test suite without the tests marked slow
	uv run pytest -n 4 -m "not slow"

max-loc: ## Enforce 777-line per-file cap
	python3 scripts/check_max_loc.py

plugin-sync: ## Verify plugins/ matches the packaged assets/ mirror
	python3 scripts/check_plugin_sync.py

mutation-probe: ## Check the provider-failure tests actually assert their decisions
	python3 ci/mutation_probe.py

version-sync: ## Verify VERSION matches every plugin manifest's version field
	python3 scripts/check_version_sync.py

wheel-assets: ## Build the wheel and verify bundled assets
	ci/verify_wheel_assets.sh

wheel-install: ## Install the wheel outside the checkout and smoke-test afriend
	ci/verify_wheel_install.sh

release-distributions: ## Build and smoke-test canonical and compatibility distributions
	ci/verify_release_distributions.sh

# Materialize the composite skills projection, including deletions.
plugin-sync-copy: ## Copy canonical skill projection into the plugin
	python3 scripts/check_plugin_sync.py --copy

# Requires plantuml (brew install plantuml) and graphviz. Renders both PNG
# (for README embedding) and SVG (scalable, text-selectable) from every
# .puml under docs/architecture/. The rendered files are committed because
# the README references them by absolute raw.githubusercontent URL.
diagrams: ## Re-render docs/architecture/*.puml to PNG + SVG
	plantuml -tpng docs/architecture/*.puml
	plantuml -tsvg docs/architecture/*.puml
	python3 scripts/write_diagram_manifest.py

# Renderability only, so it survives PlantUML's own layout changes between
# releases. Nothing ran `diagrams` automatically, and two sources sat
# unrenderable for days behind PNGs that could not be reproduced from them.
diagrams-check: ## Verify every .puml renders and no committed render is an error image
	ci/verify_diagrams_render.sh

quality: lint type-check max-loc plugin-sync version-sync diagrams-check wheel-assets wheel-install release-distributions test mutation-probe ## Run all portable quality gates

check: quality ## Alias for quality

# Local CI via act (see .actrc). `env -u DOCKER_HOST` keeps a Colima/Docker
# Desktop DOCKER_HOST from conflicting with .actrc's daemon-socket setting.
act-dry: ## List CI jobs without running them (validates the workflow + .actrc)
	env -u DOCKER_HOST act --list

act-ci: ## Run the CI quality job locally via act (slow; pulls an image first run)
	# Privilege is limited to act's disposable job container. The Linux gate
	# deliberately starts bubblewrap inside Docker, which requires nested
	# namespace creation; --init preserves the process-reaping parity in .actrc.
	env -u DOCKER_HOST act -j quality --matrix python-version:3.13 --rm \
		--container-options '--init --privileged'

# See plugins/afriend/evals/README.md. The checker reads the newest run under
# results/ and fails unless every expected case chose its skill in every run.
eval-claude: ## Live eval: which skill Claude Code selects, asserted per run
	claude plugin eval plugins/afriend --ablation none --keep-temp --no-publish --runs $(EVAL_RUNS)
	python3 scripts/check_eval_skill_selection.py plugins/afriend/evals/results

# Codex runs in a container holding no other model CLI, logged in to its own
# account: build and log in once, then run eval-codex.
eval-codex-build: ## Build the Codex eval image (once per Codex version)
	python3 scripts/run_codex_skill_eval.py build

eval-codex-login: ## Log the Codex eval's own account in (once)
	python3 scripts/run_codex_skill_eval.py login

eval-codex: ## Live eval: which skill Codex selects, in its container
	python3 scripts/run_codex_skill_eval.py run --runs $(EVAL_RUNS)

# See evals/friends/README.md. afriend exits 1 when a crossexam leaves claims
# undecided, which make reports as an error; the run can still be scored.
eval-friends: ## Live eval: crossexam spec v2 with codex, agy and a fresh claude worker
	run=$$(python3 scripts/friend_eval.py artifact --out $(FRIEND_EVAL_DIR)/spec-v2.md) \
		&& eval "$$run"

eval-friends-score: ## Score the friend eval run (FRIEND_EVAL_METHOD=1, 2 or 3)
	python3 scripts/friend_eval.py score $(FRIEND_EVAL_RUN) --method $(FRIEND_EVAL_METHOD) \
		$(if $(FRIEND_EVAL_MAPPING),--mapping $(FRIEND_EVAL_MAPPING))
