"""Assets whose bytes are pinned by digest must check out byte-exact everywhere.

Git for Windows converts text to CRLF on checkout unless told otherwise, and a
workspace asset's recorded sha256 is of its LF bytes -- so on a Windows
checkout every run refused its own harness file as a digest mismatch.
"""

from pathlib import Path
import subprocess
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "afriend" / "assets"

pytestmark = pytest.mark.git


def _digest_pinned_sources() -> list[str]:
    sources = []
    for adapter in sorted((ASSETS / "adapters").glob("*.toml")):
        for asset in tomllib.loads(adapter.read_text(encoding="utf-8")).get("workspace_assets", []):
            sources.append(f"src/afriend/assets/{asset['source']}")
    return sources


def test_some_asset_is_pinned_by_digest():
    assert _digest_pinned_sources()


@pytest.mark.parametrize("source", _digest_pinned_sources())
def test_a_digest_pinned_asset_checks_out_with_lf_on_every_platform(source):
    completed = subprocess.run(
        ["git", "check-attr", "eol", "--", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip().endswith(": eol: lf"), completed.stdout
