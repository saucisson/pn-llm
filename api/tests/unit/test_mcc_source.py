import io
import tarfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.domain.errors import ConflictError
from app.infrastructure.mcc_source import MccDirectory
from tests.unit.test_mcc import PAGE


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    (root / "archives").mkdir(parents=True)
    (root / "models.php").write_text(PAGE)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in (("Big/PT/big-1.pnml", b"<pnml/>"), ("Big/readme.txt", b"hi")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (root / "archives" / "Big-pnml.tar.gz").write_bytes(buffer.getvalue())
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", root
    server.shutdown()
    server.server_close()


def test_the_catalog_and_nets_are_downloaded_then_read_from_disk(site, tmp_path):
    url, root = site
    source = MccDirectory(directory=tmp_path / "cache", base_url=url)
    big = source.catalog()[0]
    nets = list(source.nets(family=big))
    assert [(n.instance.instance, n.payload) for n in nets] == [("big-1", b"<pnml/>")]
    (root / "archives" / "Big-pnml.tar.gz").unlink()  # a second read needs no network
    assert len(list(source.nets(family=big))) == 1


def test_a_partial_download_is_completed(site, tmp_path):
    url, root = site
    full = (root / "archives" / "Big-pnml.tar.gz").read_bytes()
    cache = tmp_path / "cache"
    (cache / "archives").mkdir(parents=True)
    (cache / "archives" / "Big-pnml.tar.gz.part").write_bytes(full[:10])
    source = MccDirectory(directory=cache, base_url=url)
    list(source.nets(family=source.catalog()[0]))
    assert (cache / "archives" / "Big-pnml.tar.gz").read_bytes() == full


def test_a_file_that_changed_since_the_first_download_is_refused(site, tmp_path):
    url, _ = site
    cache = tmp_path / "cache"
    source = MccDirectory(directory=cache, base_url=url)
    big = source.catalog()[0]
    list(source.nets(family=big))
    (cache / "archives" / "Big-pnml.tar.gz").write_bytes(b"tampered")
    with pytest.raises(ConflictError):
        list(source.nets(family=big))
