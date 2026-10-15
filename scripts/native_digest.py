"""Print the digest of the sources that decide what the native engine answers.

Results are cached by the engine's version, so a change to an algorithm (or to the models its
results are made of) must come with a new version. ``engines/native/DIGEST`` holds the digest
the current version was released with; a test fails when they differ.
Usage: ``python3 scripts/native_digest.py`` prints it; ``--write`` updates the file.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = ROOT / "api" / "app" / "domain"
DIGEST_FILE = ROOT / "engines" / "native" / "DIGEST"
SOURCES = (
    *sorted((DOMAIN / "analyses").glob("*.py")),
    DOMAIN / "operations.py",
    DOMAIN / "net_structure.py",
    DOMAIN / "inspection.py",
    DOMAIN / "contract.py",
)


def digest() -> str:
    """Return the SHA-256 of the sources, by path and content."""
    sha = hashlib.sha256()
    for path in SOURCES:
        sha.update(path.relative_to(ROOT).as_posix().encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


if __name__ == "__main__":
    current = digest()
    if "--write" in sys.argv[1:]:
        DIGEST_FILE.write_text(current + "\n")
    print(current)  # noqa: T201  (command output)
