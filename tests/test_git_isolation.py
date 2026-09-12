"""Suite-wide git isolation, asserted rather than assumed."""

import os
import subprocess

from e2e_helpers import _env
import pytest

pytestmark = pytest.mark.git


def test_global_git_config_is_neutralized_for_every_test():
    """One autouse fixture, not a per-fixture incantation nine times over.

    `git config commit.gpgsign false` appears at nine call sites in two
    spellings, and two more git-using modules set nothing -- so the release's
    one new annotated-tag test inherited `tag.gpgsign` from the developer's
    own config, which the per-site version never covered.
    """
    assert os.environ.get("GIT_CONFIG_GLOBAL") == os.devnull
    assert os.environ.get("GIT_CONFIG_SYSTEM") == os.devnull


def test_a_repository_created_in_a_test_inherits_no_signing_config(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key in ("commit.gpgsign", "tag.gpgsign", "gpg.format", "core.hooksPath"):
        got = subprocess.run(
            ["git", "-C", str(tmp_path), "config", "--get", key],
            capture_output=True,
            text=True,
        )
        assert got.returncode != 0, f"{key} leaked in as {got.stdout.strip()!r}"


def test_the_e2e_env_allowlist_forwards_the_git_config_neutralizers():
    """The autouse fixture alone reaches nothing here.

    `_env()` builds a FIXED dict and forwards only HOME, so roughly forty
    end-to-end git invocations would still read `~/.gitconfig` through HOME
    while the conftest variable never reached them. "One place" is two.
    """
    env = _env()

    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull
