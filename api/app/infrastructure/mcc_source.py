"""Contest data on disk: catalog page and family archives, downloaded resumably and checked."""

from __future__ import annotations

import hashlib
import tarfile
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from app.domain.errors import ConflictError, InvalidRequestError
from app.domain.mcc import (
    MccFamily,
    MccNetFile,
    instance_of,
    parse_catalog,
)

CHUNK = 1 << 20
TIMEOUT_S = 60


class MccDirectory:
    """Contest files under a directory; anything missing is downloaded from ``base_url``."""

    def __init__(self, *, directory: Path, base_url: str) -> None:
        self._directory = directory
        self._base_url = base_url.rstrip("/")

    def catalog(self) -> tuple[MccFamily, ...]:
        """Return the families of the contest, downloading the models page once."""
        page = self._fetch(path="models.php")
        return parse_catalog(page=page.read_text(encoding="utf-8", errors="replace"))

    def nets(self, *, family: MccFamily) -> Iterator[MccNetFile]:
        """Yield the nets of a family archive, one at a time to bound memory."""
        archive = self._fetch(path=family.archive_path)
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                instance = instance_of(family=family, member=member.name)
                content = tar.extractfile(member) if member.isfile() else None
                if instance is not None and content is not None:
                    yield MccNetFile(instance=instance, payload=content.read())

    def _fetch(self, *, path: str) -> Path:
        """Return the local copy of ``path``, resuming a partial download and checking the hash.

        The contest publishes no checksum, so the first complete download records its SHA-256
        next to the file and every later read must match it (trust on first use).
        """
        target = self._directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        sidecar = target.with_name(target.name + ".sha256")
        if not target.exists():
            partial = target.with_name(target.name + ".part")
            request = urllib.request.Request(f"{self._base_url}/{path}")  # noqa: S310 - http(s) base url from settings
            offset = partial.stat().st_size if partial.exists() else 0
            if offset:
                request.add_header("Range", f"bytes={offset}-")
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - same
                resumed = response.status == 206  # noqa: PLR2004 - HTTP partial content
                with partial.open("ab" if resumed else "wb") as out:
                    while chunk := response.read(CHUNK):
                        out.write(chunk)
            partial.replace(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if not sidecar.exists():
            sidecar.write_text(digest)
        elif sidecar.read_text().strip() != digest:
            raise ConflictError(f"{path} differs from the copy first downloaded")
        if target.stat().st_size == 0:
            raise InvalidRequestError(f"{path} is empty")
        return target
