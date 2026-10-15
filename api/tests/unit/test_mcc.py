import pytest

from app.domain.errors import InvalidRequestError
from app.domain.mcc import MccNetType, instance_of, parse_catalog

PAGE = """<table>
<tr><td class="benchmarks-headcell-name">Name</td></tr>
<tr>
   <td class="benchmarks-info-centered"><a class="model" href="pdf/Big-form.pdf">Big<span>
      <h4>Big &amp; Co, proposed by A</h4>
      <p>it models <i>a big</i> thing</p></span></a></td>
   <td class="benchmarks-info-centered">P/T</td>
   <td class="benchmarks-info-centered">Yes</td>
   <td class="benchmarks-info-centered">
      <b>Places:</b> up to 348,
      <b>Transitions:</b> up to 79094,
      <b>Arcs:</b> up to 2458524
   </td>
   <td><a href="pdf/Big-form.pdf"></a></td>
   <td><a href="archives/Big-pnml.tar.gz"></a></td>
</tr>
<tr>
   <td><a class="model" href="pdf/Fs-form.pdf">Fs<span>
      <h4>Fs</h4>
      <p>idiom</p></span></a></td>
   <td>Colored +<br />P/T equiv</td>
   <td>No</td>
   <td><b>Places:</b> 11, <b>Transitions:</b> 7, <b>Arcs:</b> 25</td>
   <td></td>
   <td><a href="archives/Fs-pnml.tar.gz"></a></td>
</tr>
<tr>
   <td><a class="model" href="pdf/Col-form.pdf">Col<span><h4>C</h4><p>d</p></span></a></td>
   <td>Colored</td><td>Yes</td><td></td><td></td>
   <td><a href="archives/Col-pnml.tar.gz"></a></td>
</tr></table>"""


def test_families_are_read_in_page_order_with_their_data():
    big, fs, col = parse_catalog(page=PAGE)
    assert (big.name, big.title, big.description) == (
        "Big",
        "Big & Co, proposed by A",
        "it models a big thing",
    )
    assert (big.net_type, big.scalable) == (MccNetType.PT, True)
    assert (big.size.places, big.size.transitions, big.size.arcs) == (348, 79094, 2458524)
    assert big.size.is_upper_bound is True
    assert big.archive_path == "archives/Big-pnml.tar.gz"
    assert big.form_path == "pdf/Big-form.pdf"
    assert (fs.net_type, fs.scalable, fs.size.is_upper_bound) == (
        MccNetType.COLORED_WITH_PT,
        False,
        False,
    )
    assert (col.net_type, col.size.places) == (MccNetType.COLORED, None)


def test_a_page_without_family_is_refused():
    with pytest.raises(InvalidRequestError):
        parse_catalog(page="<html>moved</html>")


def test_archive_members_become_instances_and_others_are_skipped():
    family = parse_catalog(page=PAGE)[0]
    pt = instance_of(family=family, member="Big/PT/big-100.pnml")
    col = instance_of(family=family, member="Big/COL/big-5.pnml")
    assert (pt.instance, pt.net_type, pt.family) == ("big-100", MccNetType.PT, "Big")
    assert col.net_type is MccNetType.COLORED
    assert instance_of(family=family, member="Big/PT/") is None
    assert instance_of(family=family, member="Big/PT/readme.txt") is None
    assert instance_of(family=family, member="x.pnml") is None
