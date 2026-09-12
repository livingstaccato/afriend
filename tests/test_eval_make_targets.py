"""The live evals are one `make` target away, and never part of `quality`.

Three evals measure things the test suite cannot: which skill Claude Code
selects, which skill Codex selects, and whether friends find real defects.
Each makes real model calls on the operator's own logins, so none belongs in
the gate CI runs -- and until they had targets, none was discoverable from the
places a contributor looks: the README's development section, AGENTS.md, and
the docs index.
"""

from pathlib import Path
import re
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
EVAL_READMES = ("plugins/afriend/evals/README.md", "evals/friends/README.md")
# What each target's recipe must run, as `make -n` prints it.
EVAL_TARGETS = {
    "eval-claude": (
        "claude plugin eval plugins/afriend --ablation none --keep-temp --no-publish --runs 2",
        "scripts/check_eval_skill_selection.py plugins/afriend/evals/results",
    ),
    "eval-codex-build": ("scripts/run_codex_skill_eval.py build",),
    "eval-codex-login": ("scripts/run_codex_skill_eval.py login",),
    "eval-codex": ("scripts/run_codex_skill_eval.py run --runs 2",),
    "eval-friends": ("scripts/friend_eval.py artifact --out",),
    "eval-friends-score": ("scripts/friend_eval.py score", "--method 3"),
}


def _makefile():
    # Make joins a backslash-newline into one logical line; read it the same way.
    return MAKEFILE.read_text().replace("\\\n", " ")


def _prerequisites(target):
    match = re.search(rf"^{re.escape(target)}:([^#\n]*)", _makefile(), re.MULTILINE)
    assert match, f"the Makefile has no `{target}` target"
    return match.group(1).split()


def test_no_live_eval_is_a_prerequisite_of_the_gate():
    gate = set(_prerequisites("quality")) | set(_prerequisites("check"))

    assert not [target for target in gate if target.startswith("eval")]


@pytest.mark.parametrize(("target", "recipe"), EVAL_TARGETS.items())
def test_each_live_eval_has_a_documented_target_that_runs_its_script(target, recipe):
    text = _makefile()

    assert re.search(rf"^{re.escape(target)}:.*## \S", text, re.MULTILINE), (
        f"`{target}` has no help"
    )
    assert target in re.search(r"^\.PHONY:(.*)$", text, re.MULTILINE).group(1).split()
    # `make -n` prints the recipe and runs none of it.
    proc = subprocess.run(
        ["make", "-n", target], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    for fragment in recipe:
        assert fragment in proc.stdout


@pytest.mark.parametrize("doc", ["README.md", "AGENTS.md", "docs/README.md"])
def test_contributor_docs_point_at_every_eval(doc):
    text = (REPO / doc).read_text()

    for readme in EVAL_READMES:
        assert readme in text, f"{doc} does not point at {readme}"


@pytest.mark.parametrize("doc", ["README.md", "AGENTS.md"])
def test_contributor_docs_name_the_eval_targets(doc):
    text = (REPO / doc).read_text()

    for target in ("make eval-claude", "make eval-codex", "make eval-friends"):
        assert target in text, f"{doc} does not name `{target}`"


def test_the_stated_line_cap_is_the_enforced_one():
    cap = re.search(
        r"^MAX_LINES = (\d+)$", (REPO / "scripts/check_max_loc.py").read_text(), re.MULTILINE
    ).group(1)

    for path in (".github/workflows/ci.yml", "Makefile"):
        stated = set(re.findall(r"(\d+)-line per-file cap", (REPO / path).read_text()))
        assert stated == {cap}, (
            f"{path} states a {sorted(stated)}-line cap; the check enforces {cap}"
        )
