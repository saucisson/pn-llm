"""Model Checking Contest catalog: families parsed from the contest's models page."""

from __future__ import annotations

import html
import re
from enum import StrEnum

from .errors import InvalidRequestError
from .mcc_properties import Examination
from .models import DomainModel

ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
NAME = re.compile(
    r'class="model" href="(?P<form>[^"]+)">(?P<name>[^<]+)<span>\s*'
    r"<h4>(?P<title>.*?)</h4>\s*<p>(?P<description>.*?)</p>",
    re.DOTALL,
)
SIZE = re.compile(r"<b>(?P<what>Places|Transitions|Arcs):</b>\s*(?P<up_to>up to )?(?P<count>\d+)")
ARCHIVE = re.compile(r'href="(?P<path>archives/[^"]+-pnml\.tar\.gz)"')
TAGS = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


class MccNetType(StrEnum):
    """How the contest classifies a family."""

    PT = "pt"
    COLORED_WITH_PT = "colored_with_pt"
    COLORED = "colored"


class MccSize(DomainModel):
    """Largest size announced for a family: ``None`` when the page does not give it."""

    places: int | None = None
    transitions: int | None = None
    arcs: int | None = None
    is_upper_bound: bool = False


class MccFamily(DomainModel):
    """One model family: instances of the same model at different scales."""

    name: str
    title: str
    description: str
    net_type: MccNetType
    scalable: bool
    size: MccSize
    form_path: str
    archive_path: str


class MccInstance(DomainModel):
    """One net of a family, located by its member in the family archive."""

    family: str
    instance: str
    net_type: MccNetType
    member: str


def text_of(*, fragment: str) -> str:
    """Return the readable text of an HTML fragment, spaces collapsed."""
    return SPACES.sub(" ", html.unescape(TAGS.sub(" ", fragment))).strip()


def parse_catalog(*, page: str) -> tuple[MccFamily, ...]:
    """Return the families listed on a models page, in page order.

    Raises:
        InvalidRequestError: if the page lists no family (the layout has probably changed).
    """
    families = []
    for row in ROW.findall(page):
        name = NAME.search(row)
        archive = ARCHIVE.search(row)
        cells = CELL.findall(row)
        if name is None or archive is None or len(cells) < 4:  # noqa: PLR2004 - header rows
            continue
        kind = text_of(fragment=cells[1]).lower()
        sizes = {found["what"]: int(found["count"]) for found in SIZE.finditer(cells[3])}
        families.append(
            MccFamily(
                name=name["name"].strip(),
                title=text_of(fragment=name["title"]),
                description=text_of(fragment=name["description"]),
                net_type=(
                    MccNetType.COLORED_WITH_PT
                    if "p/t equiv" in kind
                    else MccNetType.PT
                    if kind.startswith("p/t")
                    else MccNetType.COLORED
                ),
                scalable=text_of(fragment=cells[2]).lower() == "yes",
                size=MccSize(
                    places=sizes.get("Places"),
                    transitions=sizes.get("Transitions"),
                    arcs=sizes.get("Arcs"),
                    is_upper_bound="up to" in cells[3],
                ),
                form_path=name["form"],
                archive_path=archive["path"],
            )
        )
    if not families:
        raise InvalidRequestError("The models page lists no family")
    return tuple(families)


def instance_of(*, family: MccFamily, member: str) -> MccInstance | None:
    """Return the instance an archive member holds, or ``None`` if it is not a net.

    Members look like ``Dekker/PT/dekker-100.pnml``; colored families also have ``COL``.
    """
    parts = member.split("/")
    if len(parts) < 2 or not parts[-1].endswith(".pnml"):  # noqa: PLR2004 - dir/file at least
        return None
    colored = "COL" in parts[:-1]
    return MccInstance(
        family=family.name,
        instance=parts[-1].removesuffix(".pnml"),
        net_type=MccNetType.COLORED if colored else MccNetType.PT,
        member=member,
    )


class MccNetFile(DomainModel):
    """A net of the contest with its PNML bytes, as read from a family archive."""

    instance: MccInstance
    payload: bytes


class ModelEntry(DomainModel):
    """A stored net that comes from the contest, with where it comes from."""

    net_id: str
    family: str
    instance: str
    net_type: MccNetType
    member: str


class SeedFailure(DomainModel):
    """A contest net that could not be stored, and why: skipped, never silently dropped."""

    family: str
    member: str
    reason: str


class SeedReport(DomainModel):
    """What a seeding run did."""

    families: int
    nets_stored: int
    nets_already_known: int
    property_sets_stored: int = 0
    failures: tuple[SeedFailure, ...]


class PropertyFile(DomainModel):
    """The raw XML of one examination for an instance."""

    examination: Examination
    xml: bytes


class MccInputNet(DomainModel):
    """An instance as distributed in the contest inputs: its model and its property files."""

    family: str
    instance: str
    net_type: MccNetType
    name: str
    model: bytes
    properties: tuple[PropertyFile, ...]


INPUT_NAME = re.compile(r"^(?P<family>.+?)-(?P<kind>PT|COL)-(?P<instance>.+)$")


def split_input_name(*, name: str) -> tuple[str, MccNetType, str] | None:
    """Split ``Dekker-PT-100`` into family, type and instance; ``None`` if it has no such form."""
    found = INPUT_NAME.match(name)
    if found is None:
        return None
    kind = MccNetType.PT if found["kind"] == "PT" else MccNetType.COLORED
    return found["family"], kind, found["instance"]


class SeedCandidate(DomainModel):
    """A contest net about to be stored, with the property files that come with it, if any."""

    family: str
    instance: str
    net_type: MccNetType
    member: str
    payload: bytes
    properties: tuple[PropertyFile, ...] = ()
