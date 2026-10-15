import pytest

from app.api.negotiation import JSON, PNML, media_type_of, negotiate

OFFERED = (JSON, PNML)


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        (None, JSON),
        ("", JSON),
        ("*/*", JSON),
        ("application/*", JSON),
        ("application/json", JSON),
        ("application/pnml+xml", PNML),
        ("application/pnml+xml, application/json;q=0.5", PNML),
        ("application/json;q=0.5, application/pnml+xml", PNML),
        ("text/html, application/pnml+xml;q=0.2, */*;q=0.1", PNML),
        ("application/json;q=0, */*", PNML),
        ("application/json;q=0.3, application/pnml+xml;q=0.3", JSON),
        ("text/html", None),
        ("application/xml", None),
        ("application/json;q=0, application/pnml+xml;q=0", None),
        ("application/json;q=oops", None),
    ],
)
def test_accept_header_matrix(accept, expected):
    assert negotiate(accept=accept, offered=OFFERED) == expected


def test_media_type_drops_parameters_and_case():
    assert media_type_of(content_type="Application/JSON; charset=utf-8") == "application/json"
    assert media_type_of(content_type=None) == ""
