import pytest

from app.domain.errors import InvalidNetError
from app.domain.net_document import PTNET_TYPE_URI, Annotation, NetDocument, Page, Place, Transition
from app.domain.nets import summarize_document
from tests.support import MUTEX_DOCUMENT


def test_counts_and_tokens_of_a_pt_net():
    summary = summarize_document(document=MUTEX_DOCUMENT, net_id="abc")
    assert (summary.places, summary.transitions, summary.arcs, summary.pages) == (3, 2, 6, 1)
    assert summary.initial_tokens == 2
    assert summary.kind == "pt"
    assert summary.source_id == "mutex"


def test_counts_include_nested_pages():
    document = NetDocument(
        source_id="n",
        type_uri=PTNET_TYPE_URI,
        pages=(
            Page(
                id="a",
                places=(Place(id="p"),),
                pages=(Page(id="b", transitions=(Transition(id="t"),)),),
            ),
        ),
    )
    summary = summarize_document(document=document, net_id="x")
    assert (summary.places, summary.transitions, summary.pages) == (1, 1, 2)
    assert summary.initial_tokens == 0


def test_tokens_are_not_defined_for_colored_nets():
    document = NetDocument(
        source_id="n",
        type_uri="http://www.pnml.org/version-2009/grammar/symmetricnet",
        places=(Place(id="p", initial_marking=Annotation(text="1`dot")),),
        transitions=(Transition(id="t"),),
    )
    assert summarize_document(document=document, net_id="x").initial_tokens is None


@pytest.mark.parametrize(
    "document",
    [
        NetDocument(source_id="n", type_uri=PTNET_TYPE_URI),
        NetDocument(source_id="n", type_uri=PTNET_TYPE_URI, places=(Place(id="p"),)),
        NetDocument(source_id="n", type_uri=PTNET_TYPE_URI, transitions=(Transition(id="t"),)),
    ],
)
def test_a_net_needs_a_place_and_a_transition(document):
    with pytest.raises(InvalidNetError, match="Empty net"):
        summarize_document(document=document, net_id="x")
