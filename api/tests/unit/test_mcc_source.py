import io
import tarfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.domain.errors import ConflictError
from app.infrastructure.mcc_source import MccDirectory
from tests.support import MUTEX_PNML
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
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as tar:
        for name, data in (
            ("Big-PT-7/model.pnml", MUTEX_PNML),
            ("Big-PT-7/CTLCardinality.xml", b"<property-set/>"),
            ("Big-PT-7/instance", b"x"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    outer = io.BytesIO()
    with tarfile.open(fileobj=outer, mode="w:gz") as tar:
        for name, data in (
            ("INPUTS-2026/Big-PT-7.tgz", inner.getvalue()),
            ("INPUTS-2026/Other-PT-1.tgz", inner.getvalue()),
            ("INPUTS-2026/notaninstance.tgz", b"x"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (root / "archives" / "INPUTS-2026.tar.gz").write_bytes(outer.getvalue())
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


def test_inputs_give_each_instance_its_model_and_property_files(site, tmp_path):
    url, _ = site
    source = MccDirectory(directory=tmp_path / "cache", base_url=url)
    found = list(source.inputs(only_families=("Big",)))
    assert [(n.family, n.instance, n.net_type.value, n.name) for n in found] == [
        ("Big", "7", "pt", "Big-PT-7")
    ]
    assert found[0].model == MUTEX_PNML
    assert [(f.examination, f.xml) for f in found[0].properties] == [
        ("CTLCardinality", b"<property-set/>")
    ]
    assert len(list(source.inputs(only_families=()))) == 2


def test_the_published_results_are_read_from_their_archive_with_provenance(site, tmp_path):
    url, root = site
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = b"a,b\n1,2\n"
        info = tarfile.TarInfo("GlobalSummary.csv")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (root / "archives" / "GlobalSummary.csv.tar.gz").write_bytes(buffer.getvalue())
    source = MccDirectory(directory=tmp_path / "cache", base_url=url)
    file = source.result_file()
    assert file.url == f"{url}/archives/GlobalSummary.csv.tar.gz"
    assert len(file.sha256) == 64
    assert list(source.result_lines()) == ["a,b\n", "1,2\n"]
