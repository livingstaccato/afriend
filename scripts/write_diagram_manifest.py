"""Record source and PNG digests after ``make diagrams`` renders them."""

from hashlib import sha256
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPO / "docs" / "architecture"
MANIFEST = ARCHITECTURE / "diagram-digests.json"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    entries: dict[str, dict[str, str]] = {}
    for source in sorted(ARCHITECTURE.glob("*.puml")):
        png = source.with_suffix(".png")
        if not png.is_file():
            raise SystemExit(f"missing rendered PNG for {source.name}")
        entries[source.stem] = {
            "puml_sha256": digest(source),
            "png_sha256": digest(png),
        }
    MANIFEST.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
