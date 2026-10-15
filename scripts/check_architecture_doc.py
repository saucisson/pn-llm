"""Check that docs/architecture.md describes the code: used as a pre-commit hook and in CI.

Fails when a module under api/app/ is missing from the module table, or when the document
mentions a module that does not exist. Keeps the stored documentation from drifting.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "api" / "app"
DOC = ROOT / "docs" / "architecture.md"
MODULE_REFERENCE = re.compile(r"`(app/[\w/]+\.py)`")


def main() -> int:
    """Return 0 when the documentation matches the modules, 1 otherwise."""
    documented = set(MODULE_REFERENCE.findall(DOC.read_text()))
    existing = {
        f"app/{path.relative_to(APP).as_posix()}"
        for path in APP.rglob("*.py")
        if path.name != "__init__.py"
    }

    missing = sorted(existing - documented)
    stale = sorted(documented - existing)
    for module in missing:
        print(f"docs/architecture.md does not describe `{module}`")  # noqa: T201  (hook output)
    for module in stale:
        print(f"docs/architecture.md mentions `{module}`, which does not exist")  # noqa: T201  (hook output)
    if missing or stale:
        print("Update the module table in docs/architecture.md in the same commit.")  # noqa: T201  (hook output)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
