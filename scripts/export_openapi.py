"""Write the OpenAPI document of the API to docs/openapi.json, or check it is current.

Usage: ``python3 scripts/export_openapi.py`` writes; ``--check`` fails when the file is stale.
The UI generates its TypeScript types from this file, so an API change that is not exported
fails the hook and the CI instead of the browser.
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from app.main import create_app  # noqa: E402  (needs the path above)
from app.settings import Settings  # noqa: E402

TARGET = ROOT / "docs" / "openapi.json"


def main() -> int:
    """Return 0 when done (or current in check mode), 1 when the file is stale."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(settings=Settings(database_path=Path(tmp) / "openapi.sqlite"))
        text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv[1:]:
        if TARGET.exists() and TARGET.read_text() == text:
            return 0
        print("stale OpenAPI document: run python3 scripts/export_openapi.py")  # noqa: T201  (hook output)
        return 1
    TARGET.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
