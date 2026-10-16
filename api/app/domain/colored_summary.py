"""A summary of a colored net at the colored level: sorts, groups of places and transitions, sizes.

It never enumerates the unfolded net: it says how big the unfolding would be, from the sizes of the
sorts and the variables each transition uses, so that someone (or the LLM) can decide whether to
unfold. Names are the ones of the net.
"""

from __future__ import annotations

import math
from collections import defaultdict

from pydantic import Field

from .colored import (
    AliasSort,
    Declarations,
    EnumerationSort,
    IntegerRangeSort,
    ProductSort,
    UnsupportedColoredError,
    children,
    read_declarations,
    sort_size,
)
from .colored_terms import (
    AddTerm,
    AllTerm,
    ConstantTerm,
    DotTerm,
    NumberOfTerm,
    PredecessorTerm,
    SubtractTerm,
    SuccessorTerm,
    Term,
    TupleTerm,
    VariableTerm,
    read_annotation_guard,
    read_annotation_term,
    variables_of_guard,
    variables_of_term,
)
from .contract import ElementRef
from .models import DomainModel
from .net_document import Arc, NetDocument, Place, Transition


class SortSummary(DomainModel):
    """A sort, its size, and how it is built."""

    id: str
    name: str
    kind: str
    size: int
    detail: str


class PlaceGroup(DomainModel):
    """Places with the same domain."""

    sort: str
    domain_size: int
    count: int
    examples: tuple[ElementRef, ...]


class TransitionGroup(DomainModel):
    """Transitions that use the same variables."""

    variables: tuple[str, ...]
    bindings_upper_bound: int
    count: int
    with_guard: int
    examples: tuple[ElementRef, ...]


class ArcFunctionCount(DomainModel):
    """How many arc inscriptions use one kind of color function."""

    function: str
    count: int


class UnfoldedEstimate(DomainModel):
    """How big the unfolded P/T net would be, at most (guards can only make it smaller)."""

    places: int
    transitions_upper_bound: int
    arcs_estimate: int


class ColoredSummary(DomainModel):
    """The colored net at a glance."""

    sorts: tuple[SortSummary, ...]
    place_groups: tuple[PlaceGroup, ...]
    transition_groups: tuple[TransitionGroup, ...]
    arc_functions: tuple[ArcFunctionCount, ...]
    unfolded: UnfoldedEstimate
    note: str = Field(
        default="Sizes are exact for places and an upper bound for transitions; the arc figure is "
        "an estimate (an `all` inscription counts the whole domain)."
    )


def describe_sort(*, declarations: Declarations, sort_id: str) -> SortSummary:
    """Summarize one sort."""
    sort = declarations.sort(sort_id=sort_id)
    size = sort_size(declarations=declarations, sort_id=sort_id)
    if isinstance(sort, EnumerationSort):
        names = ", ".join(c.name for c in sort.constants[:6])
        more = "" if len(sort.constants) <= 6 else ", ..."  # noqa: PLR2004 - how many values are named
        detail = f"{'cyclic ' if sort.cyclic else ''}enumeration: {names}{more}"
    elif isinstance(sort, IntegerRangeSort):
        detail = f"integers {sort.start}..{sort.end}"
    elif isinstance(sort, ProductSort):
        detail = " x ".join(declarations.sort(sort_id=c).name for c in sort.components)
    elif isinstance(sort, AliasSort):
        detail = f"another name for {declarations.sort(sort_id=sort.target).name}"
    else:
        detail = "a single value"
    return SortSummary(id=sort.id, name=sort.name, kind=sort.kind, size=size, detail=detail)


def functions_of(*, term: Term) -> frozenset[str]:  # noqa: PLR0911 - one return per kind of term
    """Name the kinds of color function a term uses."""
    if isinstance(term, VariableTerm):
        return frozenset({"variable"})
    if isinstance(term, ConstantTerm):
        return frozenset({"constant"})
    if isinstance(term, DotTerm):
        return frozenset({"dot"})
    if isinstance(term, AllTerm):
        return frozenset({"all"})
    if isinstance(term, TupleTerm):
        return frozenset({"tuple"}).union(*(functions_of(term=t) for t in term.items))
    if isinstance(term, SuccessorTerm | PredecessorTerm):
        name = "successor" if isinstance(term, SuccessorTerm) else "predecessor"
        return frozenset({name}) | functions_of(term=term.argument)
    if isinstance(term, NumberOfTerm):
        weighted = frozenset({"weighted"}) if term.count > 1 else frozenset()
        return weighted | functions_of(term=term.item)
    if isinstance(term, AddTerm):
        return frozenset({"sum"}).union(*(functions_of(term=t) for t in term.arguments))
    if isinstance(term, SubtractTerm):
        return (
            frozenset({"difference"}) | functions_of(term=term.left) | functions_of(term=term.right)
        )
    return frozenset()


def summarize_colored(*, document: NetDocument, examples: int = 3) -> ColoredSummary:
    """Summarize a colored net.

    Raises:
        UnsupportedColoredError: if the net is not a symmetric net, or uses a construct outside
            the supported vocabulary or an undeclared sort or variable.
    """
    if document.kind != "symmetric":
        raise UnsupportedColoredError(
            f"The colored summary reads symmetric nets, not {document.kind!r} nets"
        )
    declarations = read_declarations(document=document)
    sizes = {s.id: sort_size(declarations=declarations, sort_id=s.id) for s in declarations.sorts}
    variable_sort = {v.id: v.sort for v in declarations.variables}

    places: list[Place] = []
    transitions: list[Transition] = []
    arcs: list[Arc] = []
    for located in document.located_containers():
        places.extend(located.container.places)
        transitions.extend(located.container.transitions)
        arcs.extend(located.container.arcs)

    def ref(*, item: Place | Transition, kind: str) -> ElementRef:
        return ElementRef(
            id=item.id,
            name=None if item.name is None else item.name.text,
            kind=kind,
        )

    # Places by domain.
    domain_of: dict[str, str] = {}
    by_sort: dict[str, list[Place]] = defaultdict(list)
    for place in places:
        node = None if place.place_type is None else place.place_type.structure
        inner = () if node is None else children(node=node)
        if not inner:
            raise UnsupportedColoredError(f"The place {place.id!r} has no declared sort")
        sort_id = (
            "dot"
            if inner[0].name.endswith("}dot") or inner[0].name == "dot"
            else next((a.value for a in inner[0].attributes if a.name == "declaration"), "")
        )
        if sort_id != "dot" and sort_id not in sizes:
            raise UnsupportedColoredError(
                f"The place {place.id!r} has the undeclared sort {sort_id!r}"
            )
        domain_of[place.id] = sort_id
        by_sort[sort_id].append(place)
    sort_names = {s.id: s.name for s in declarations.sorts} | {"dot": "dot"}
    place_groups = tuple(
        PlaceGroup(
            sort=sort_names[sort_id],
            domain_size=sizes.get(sort_id, 1),
            count=len(group),
            examples=tuple(
                ref(item=p, kind="place") for p in sorted(group, key=lambda p: p.id)[:examples]
            ),
        )
        for sort_id, group in sorted(by_sort.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )

    # Transitions by the variables they use; arcs by the functions they carry.
    used: dict[str, set[str]] = {t.id: set() for t in transitions}
    guarded: set[str] = set()
    functions: dict[str, int] = defaultdict(int)
    arc_factor = 0
    per_transition_arcs: dict[str, int] = defaultdict(int)
    for transition in transitions:
        guard = read_annotation_guard(annotation=transition.condition)
        if guard is not None:
            guarded.add(transition.id)
            used[transition.id] |= variables_of_guard(guard=guard)
    for arc in arcs:
        term = read_annotation_term(annotation=arc.inscription)
        transition_id = arc.target if arc.target in used else arc.source
        place_id = arc.source if arc.target in used else arc.target
        if term is None:
            continue
        for function in functions_of(term=term):
            functions[function] += 1
        used[transition_id] |= variables_of_term(term=term)
        factor = (
            sizes.get(domain_of.get(place_id, "dot"), 1) if "all" in functions_of(term=term) else 1
        )
        per_transition_arcs[transition_id] += factor
        arc_factor += factor
    groups: dict[tuple[str, ...], list[Transition]] = defaultdict(list)
    bindings: dict[str, int] = {}
    for transition in transitions:
        for variable in used[transition.id]:
            if variable not in variable_sort:
                raise UnsupportedColoredError(f"The net uses the undeclared variable {variable!r}")
        names = tuple(
            sorted(
                f"{next(v.name for v in declarations.variables if v.id == i)}: "
                f"{sort_names[variable_sort[i]]}"
                for i in used[transition.id]
            )
        )
        bindings[transition.id] = math.prod(sizes[variable_sort[i]] for i in used[transition.id])
        groups[names].append(transition)
    transition_groups = tuple(
        TransitionGroup(
            variables=names,
            bindings_upper_bound=bindings[group[0].id],
            count=len(group),
            with_guard=sum(t.id in guarded for t in group),
            examples=tuple(
                ref(item=t, kind="transition") for t in sorted(group, key=lambda t: t.id)[:examples]
            ),
        )
        for names, group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )
    return ColoredSummary(
        sorts=tuple(
            describe_sort(declarations=declarations, sort_id=s.id) for s in declarations.sorts
        ),
        place_groups=place_groups,
        transition_groups=transition_groups,
        arc_functions=tuple(
            ArcFunctionCount(function=name, count=count)
            for name, count in sorted(functions.items())
        ),
        unfolded=UnfoldedEstimate(
            places=sum(sizes.get(domain_of[p.id], 1) for p in places),
            transitions_upper_bound=sum(bindings.values()),
            arcs_estimate=sum(bindings[t] * f for t, f in per_transition_arcs.items()),
        ),
    )
