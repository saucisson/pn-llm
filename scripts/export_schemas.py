"""Write the JSON Schemas of the public models into docs/schemas/, or check they are current.

Usage: ``python3 scripts/export_schemas.py`` writes; ``--check`` fails when a file is stale.
Used as a pre-commit hook and in CI so that the committed schemas never drift from the models.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from app.domain.schemas import EXPORTED_MODELS, render_schema  # noqa: E402  (needs the path above)

SCHEMAS = ROOT / "docs" / "schemas"


def main() -> int:
    """Return 0 when done (or when current in check mode), 1 when a schema is stale."""
    check = "--check" in sys.argv[1:]
    stale = 0
    SCHEMAS.mkdir(exist_ok=True)
    expected_files = set()
    for model in EXPORTED_MODELS:
        path = SCHEMAS / f"{model.__name__}.schema.json"
        expected_files.add(path)
        text = render_schema(model=model)
        if path.exists() and path.read_text() == text:
            continue
        if check:
            print(f"stale JSON Schema: {path.relative_to(ROOT)}")  # noqa: T201  (hook output)
            stale += 1
        else:
            path.write_text(text)
    for path in sorted(set(SCHEMAS.glob("*.schema.json")) - expected_files):
        if check:
            print(f"orphan JSON Schema: {path.relative_to(ROOT)}")  # noqa: T201  (hook output)
            stale += 1
        else:
            path.unlink()
    if stale:
        print("Run: python3 scripts/export_schemas.py")  # noqa: T201  (hook output)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
