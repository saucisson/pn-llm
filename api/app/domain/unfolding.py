"""Unfold a colored (symmetric) net into the P/T net it stands for, with the mapping back.

A colored place with a sort of ``n`` values becomes ``n`` places, one per color; a colored
transition becomes one transition per assignment of its variables that satisfies its guard and for
which every inscription is defined. Inscriptions become arcs weighted by multiplicity. The mapping
keeps, for every unfolded place, the colored place and color it stands for and, for every unfolded
transition, the colored transition and the binding (docs/colored-nets.md), so that results found on
the unfolded net are reported on the colored one. The unfolding is bounded: a net whose unfolding
would be too large is refused with a clear error instead of exhausting memory.
"""

from __future__ import annotations

import itertools
from collections import Counter

from pydantic import Field

from .colored import (
    AliasSort,
    Declarations,
    EnumerationSort,
    IntegerRangeSort,
    ProductSort,
    UnsupportedColoredError,
    place_sort_id,
    read_declarations,
)
from .colored_terms import (
    AddTerm,
    AllTerm,
    Comparison,
    ConstantTerm,
    DotTerm,
    Guard,
    Junction,
    Negation,
    NumberOfTerm,
    NumberTerm,
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
from .contract import Assignment
from .errors import InvalidRequestError
from .models import DomainModel
from .net_document import Arc, NetDocument, Place, Transition
from .net_structure import NetStructure, StructureArc, StructureNode
from .reductions.document import structure_to_document

type Value = str | int | tuple[Value, ...]


class UnfoldingTooLargeError(InvalidRequestError):
    """The unfolding would exceed a limit: unfold a smaller instance or raise the limits."""


class UnfoldLimits(DomainModel):
    """How large an unfolding may get."""

    max_places: int = Field(default=200_000, ge=1)
    max_transitions: int = Field(default=200_000, ge=1)
    max_arcs: int = Field(default=1_000_000, ge=1)


class UnfoldedPlace(DomainModel):
    """An unfolded place and the colored place and color it stands for."""

    original: str
    color: str
    unfolded: str


class UnfoldedTransition(DomainModel):
    """An unfolded transition and the colored transition and binding it stands for."""

    original: str
    binding: tuple[Assignment, ...]
    unfolded: str


class UnfoldingMapping(DomainModel):
    """The relation between the unfolded net and the colored one."""

    places: tuple[UnfoldedPlace, ...]
    transitions: tuple[UnfoldedTransition, ...]


class Unfolded(DomainModel):
    """The unfolded P/T net, as a document, and the way back."""

    document: NetDocument
    mapping: UnfoldingMapping


class UndefinedError(Exception):
    """A term has no value for this binding (the successor of the last value of a range)."""


class Domains:
    """The values of the sorts of a net, and how to name and order them."""

    def __init__(self, *, declarations: Declarations) -> None:
        """Index the declarations."""
        self.declarations = declarations
        self.constant_sort = {
            c.id: s.id
            for s in declarations.sorts
            if isinstance(s, EnumerationSort)
            for c in s.constants
        }
        self.constant_name = {
            c.id: c.name
            for s in declarations.sorts
            if isinstance(s, EnumerationSort)
            for c in s.constants
        }
        self.variable_sort = {v.id: v.sort for v in declarations.variables}

    def resolve(self, *, sort_id: str) -> str:
        """Follow aliases to the sort that defines the values."""
        sort = self.declarations.sort(sort_id=sort_id)
        return self.resolve(sort_id=sort.target) if isinstance(sort, AliasSort) else sort.id

    def values(self, *, sort_id: str) -> tuple[Value, ...]:
        """Return the values of a sort, in the order of its definition."""
        sort = self.declarations.sort(sort_id=self.resolve(sort_id=sort_id))
        if isinstance(sort, EnumerationSort):
            return tuple(c.id for c in sort.constants)
        if isinstance(sort, IntegerRangeSort):
            return tuple(range(sort.start, sort.end + 1))
        if isinstance(sort, ProductSort):
            return tuple(itertools.product(*(self.values(sort_id=c) for c in sort.components)))
        return ("dot",)

    def label(self, *, value: Value) -> str:
        """Name a value the way the net does: a constant's name, a number, parts joined by dots."""
        if isinstance(value, tuple):
            return ".".join(self.label(value=v) for v in value)
        if isinstance(value, int):
            return str(value)
        return self.constant_name.get(value, value)

    def step(self, *, sort_id: str, value: Value, by: int) -> Value:
        """Return the successor (``by`` 1) or predecessor (``by`` -1) of a value.

        Raises:
            UndefinedError: past the end of a range or of a non-cyclic enumeration.
        """
        sort = self.declarations.sort(sort_id=self.resolve(sort_id=sort_id))
        if isinstance(sort, IntegerRangeSort) and isinstance(value, int):
            moved = value + by
            if sort.start <= moved <= sort.end:
                return moved
            raise UndefinedError
        if isinstance(sort, EnumerationSort):
            ids = [c.id for c in sort.constants]
            moved = ids.index(str(value)) + by
            if 0 <= moved < len(ids):
                return ids[moved]
            if sort.cyclic:
                return ids[moved % len(ids)]
            raise UndefinedError
        raise UnsupportedColoredError("Successor and predecessor apply to enumerations and ranges")

    def sort_of(self, *, term: Term) -> str | None:
        """Return the sort of a term that denotes one value, when it can be told."""
        if isinstance(term, VariableTerm):
            return self.variable_sort.get(term.variable)
        if isinstance(term, ConstantTerm):
            return self.constant_sort.get(term.operator)
        if isinstance(term, SuccessorTerm | PredecessorTerm):
            return self.sort_of(term=term.argument)
        return None

    def rank(self, *, sort_id: str, value: Value) -> int:
        """Return the position of a value among its sort's values, for order comparisons."""
        if isinstance(value, int):
            return value
        sort = self.declarations.sort(sort_id=self.resolve(sort_id=sort_id))
        if isinstance(sort, EnumerationSort):
            return [c.id for c in sort.constants].index(str(value))
        raise UnsupportedColoredError("Only numbers and enumerations can be ordered")


type Environment = tuple[tuple[str, Value], ...]


def value_of(*, term: Term, domains: Domains, environment: Environment) -> Value:
    """Evaluate a term that denotes one value.

    Raises:
        UndefinedError: if a successor or predecessor falls outside its sort.
        UnsupportedColoredError: for a term that does not denote a single value.
    """
    if isinstance(term, VariableTerm):
        for name, value in environment:
            if name == term.variable:
                return value
        raise UnsupportedColoredError(f"The variable {term.variable!r} has no value here")
    if isinstance(term, ConstantTerm):
        return term.operator
    if isinstance(term, DotTerm):
        return "dot"
    if isinstance(term, NumberTerm):
        return term.value
    if isinstance(term, TupleTerm):
        return tuple(value_of(term=t, domains=domains, environment=environment) for t in term.items)
    if isinstance(term, SuccessorTerm | PredecessorTerm):
        sort_id = domains.sort_of(term=term.argument)
        if sort_id is None:
            raise UnsupportedColoredError("Cannot tell the sort of a successor's argument")
        return domains.step(
            sort_id=sort_id,
            value=value_of(term=term.argument, domains=domains, environment=environment),
            by=1 if isinstance(term, SuccessorTerm) else -1,
        )
    raise UnsupportedColoredError("This term is a multiset, not a single value")


def multiset_of(*, term: Term, domains: Domains, environment: Environment) -> Counter[Value]:
    """Evaluate an arc inscription or a marking to a multiset of values.

    Raises:
        UndefinedError: if a successor or predecessor falls outside its sort.
        UnsupportedColoredError: for a subtraction that goes below zero or an unknown construct.
    """
    if isinstance(term, AllTerm):
        return Counter(dict.fromkeys(domains.values(sort_id=term.sort), 1))
    if isinstance(term, NumberOfTerm):
        inner = multiset_of(term=term.item, domains=domains, environment=environment)
        return Counter({value: count * term.count for value, count in inner.items()})
    if isinstance(term, AddTerm):
        total: Counter[Value] = Counter()
        for argument in term.arguments:
            total.update(multiset_of(term=argument, domains=domains, environment=environment))
        return total
    if isinstance(term, SubtractTerm):
        left = multiset_of(term=term.left, domains=domains, environment=environment)
        right = multiset_of(term=term.right, domains=domains, environment=environment)
        if any(right[v] > left[v] for v in right):
            raise UnsupportedColoredError("A subtraction of multisets goes below zero")
        return left - right
    return Counter({value_of(term=term, domains=domains, environment=environment): 1})


def holds(*, guard: Guard, domains: Domains, environment: Environment) -> bool:
    """Evaluate a guard in an environment.

    Raises:
        UndefinedError: if a successor or predecessor falls outside its sort.
    """
    if isinstance(guard, Negation):
        return not holds(guard=guard.argument, domains=domains, environment=environment)
    if isinstance(guard, Junction):
        results = (
            holds(guard=g, domains=domains, environment=environment) for g in guard.arguments
        )
        return all(results) if guard.operator == "and" else any(results)
    left = value_of(term=guard.left, domains=domains, environment=environment)
    right = value_of(term=guard.right, domains=domains, environment=environment)
    if isinstance(guard, Comparison) and guard.operator in {"==", "!="}:
        return (left == right) == (guard.operator == "==")
    sort_id = domains.sort_of(term=guard.left) or domains.sort_of(term=guard.right)
    if sort_id is None and not (isinstance(left, int) and isinstance(right, int)):
        raise UnsupportedColoredError("Cannot tell the sort of an ordered comparison")
    a = left if isinstance(left, int) else domains.rank(sort_id=sort_id or "", value=left)
    b = right if isinstance(right, int) else domains.rank(sort_id=sort_id or "", value=right)
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[guard.operator]


class IdPool:
    """The ids given to unfolded elements: each one is unique, a clash gets a numbered suffix."""

    def __init__(self) -> None:
        """Start with no id taken."""
        self._taken: set[str] = set()

    def fresh(self, *, wanted: str) -> str:
        """Take the wanted id, or the first free ``wanted~n``."""
        candidate, number = wanted, 1
        while candidate in self._taken:
            number += 1
            candidate = f"{wanted}~{number}"
        self._taken.add(candidate)
        return candidate


class PlaceTable:
    """The unfolded places: their nodes, their mapping and the lookup of (place, color).

    A private working index in the manner of ``WorkingNet``: built once, then only read.
    """

    def __init__(self, *, places: list[Place], domains: Domains, ids: IdPool, limit: int) -> None:
        """Unfold every place, with its initial marking."""
        self.nodes: list[StructureNode] = []
        self.mapping: list[UnfoldedPlace] = []
        self.by_color: dict[tuple[str, Value], str] = {}
        for place in sorted(places, key=lambda p: p.id):
            values = domains.values(sort_id=place_sort_id(place=place))
            marking = read_annotation_term(annotation=place.initial_marking)
            tokens: Counter[Value] = (
                Counter()
                if marking is None
                else multiset_of(term=marking, domains=domains, environment=())
            )
            name = place.name.text if place.name is not None and place.name.text else place.id
            for value in values:
                label = domains.label(value=value)
                single = len(values) == 1
                unfolded = ids.fresh(wanted=place.id if single else f"{place.id}_{label}")
                self.by_color[(place.id, value)] = unfolded
                self.mapping.append(
                    UnfoldedPlace(original=place.id, color=label, unfolded=unfolded)
                )
                self.nodes.append(
                    StructureNode(
                        id=unfolded,
                        name=name if single else f"{name}_{label}",
                        kind="place",
                        tokens=tokens.get(value, 0),
                    )
                )
            if len(self.nodes) > limit:
                raise UnfoldingTooLargeError(f"The unfolding has more than {limit} places")
            if any((place.id, value) not in self.by_color for value in tokens):
                raise UnsupportedColoredError(
                    f"The initial marking of {place.id!r} holds a value outside its sort"
                )

    def place(self, *, key: tuple[str, Value], transition: str) -> str:
        """Return the unfolded place of a colored place and color.

        Raises:
            UnsupportedColoredError: if an inscription yields a color outside the place's sort.
        """
        if key not in self.by_color:
            raise UnsupportedColoredError(
                f"An inscription of {transition!r} yields a value outside the sort of {key[0]!r}"
            )
        return self.by_color[key]


class TransitionArcs(DomainModel):
    """The arcs a colored transition has, as (place id, inscription) on each side."""

    transition: Transition
    inputs: tuple[tuple[str, Term], ...]
    outputs: tuple[tuple[str, Term], ...]


def arcs_of_transitions(
    *, transitions: list[Transition], arcs: list[Arc], redirect: dict[str, str]
) -> tuple[TransitionArcs, ...]:
    """Attach each arc to the transition it touches, resolving reference nodes."""
    inputs: dict[str, list[tuple[str, Term]]] = {t.id: [] for t in transitions}
    outputs: dict[str, list[tuple[str, Term]]] = {t.id: [] for t in transitions}
    for arc in arcs:
        source, target = redirect.get(arc.source, arc.source), redirect.get(arc.target, arc.target)
        term = read_annotation_term(annotation=arc.inscription)
        if term is None:
            raise UnsupportedColoredError(f"The arc {arc.id!r} has no inscription")
        if target in inputs:
            inputs[target].append((source, term))
        elif source in outputs:
            outputs[source].append((target, term))
        else:
            raise UnsupportedColoredError(f"The arc {arc.id!r} does not touch a transition")
    return tuple(
        TransitionArcs(transition=t, inputs=tuple(inputs[t.id]), outputs=tuple(outputs[t.id]))
        for t in sorted(transitions, key=lambda t: t.id)
    )


class BindingUnfolding(DomainModel):
    """One unfolded transition and its arcs as (unfolded place id, weight)."""

    node: StructureNode
    mapping: UnfoldedTransition
    inputs: tuple[tuple[str, int], ...]
    outputs: tuple[tuple[str, int], ...]


def unfold_transition(
    *, colored: TransitionArcs, domains: Domains, table: PlaceTable, ids: IdPool, limit: int
) -> tuple[BindingUnfolding, ...]:
    """Unfold one colored transition: one result per binding that passes the guard.

    Raises:
        UnfoldingTooLargeError: if the transition alone has more bindings than ``limit``.
    """
    transition = colored.transition
    guard = read_annotation_guard(annotation=transition.condition)
    used: set[str] = set()
    for _, term in (*colored.inputs, *colored.outputs):
        used |= variables_of_term(term=term)
    if guard is not None:
        used |= variables_of_guard(guard=guard)
    declared = {v.id: v.name for v in domains.declarations.variables}
    for variable in used:
        if variable not in declared:
            raise UnsupportedColoredError(f"The net uses the undeclared variable {variable!r}")
    variables = sorted(used, key=lambda v: declared[v])
    value_lists = [domains.values(sort_id=domains.variable_sort[v]) for v in variables]
    bindings = 1
    for values in value_lists:
        bindings *= len(values)
    if bindings > limit:
        raise UnfoldingTooLargeError(
            f"The transition {transition.id!r} alone has {bindings} bindings, "
            f"more than the limit of {limit}"
        )
    name = (
        transition.name.text
        if transition.name is not None and transition.name.text
        else transition.id
    )
    found: list[BindingUnfolding] = []
    for combination in itertools.product(*value_lists):
        environment: Environment = tuple(zip(variables, combination, strict=True))
        try:
            if guard is not None and not holds(
                guard=guard, domains=domains, environment=environment
            ):
                continue
            sides: list[Counter[tuple[str, Value]]] = []
            for wanted in (colored.inputs, colored.outputs):
                side: Counter[tuple[str, Value]] = Counter()
                for place_id, term in wanted:
                    for value, count in multiset_of(
                        term=term, domains=domains, environment=environment
                    ).items():
                        side[(place_id, value)] += count
                sides.append(side)
        except UndefinedError:
            continue
        labels = tuple(domains.label(value=v) for v in combination)
        suffix = "_".join(labels)
        unfolded = ids.fresh(wanted=f"{transition.id}_{suffix}" if suffix else transition.id)
        found.append(
            BindingUnfolding(
                node=StructureNode(
                    id=unfolded, name=f"{name}_{suffix}" if suffix else name, kind="transition"
                ),
                mapping=UnfoldedTransition(
                    original=transition.id,
                    binding=tuple(
                        Assignment(variable=declared[v], color=label)
                        for v, label in zip(variables, labels, strict=True)
                    ),
                    unfolded=unfolded,
                ),
                inputs=tuple(
                    sorted(
                        (table.place(key=key, transition=transition.id), weight)
                        for key, weight in sides[0].items()
                    )
                ),
                outputs=tuple(
                    sorted(
                        (table.place(key=key, transition=transition.id), weight)
                        for key, weight in sides[1].items()
                    )
                ),
            )
        )
    return tuple(found)


def unfold(*, document: NetDocument, net_id: str, limits: UnfoldLimits) -> Unfolded:
    """Unfold a symmetric net.

    Raises:
        UnsupportedColoredError: if the net is not symmetric or uses a construct outside the
            supported vocabulary.
        UnfoldingTooLargeError: if the result would exceed a limit.
    """
    if document.kind != "symmetric":
        raise UnsupportedColoredError(f"Only symmetric nets can be unfolded, not {document.kind!r}")
    domains = Domains(declarations=read_declarations(document=document))
    containers = [located.container for located in document.located_containers()]
    redirect = {r.id: r.ref for c in containers for r in c.ref_places}
    redirect |= {r.id: r.ref for c in containers for r in c.ref_transitions}
    ids = IdPool()
    table = PlaceTable(
        places=[p for c in containers for p in c.places],
        domains=domains,
        ids=ids,
        limit=limits.max_places,
    )
    colored_transitions = arcs_of_transitions(
        transitions=[t for c in containers for t in c.transitions],
        arcs=[a for c in containers for a in c.arcs],
        redirect=redirect,
    )
    unfolded: list[BindingUnfolding] = []
    for colored in colored_transitions:
        unfolded.extend(
            unfold_transition(
                colored=colored, domains=domains, table=table, ids=ids, limit=limits.max_transitions
            )
        )
        if len(unfolded) > limits.max_transitions:
            raise UnfoldingTooLargeError(
                f"The unfolding has more than {limits.max_transitions} transitions"
            )
    arcs: list[StructureArc] = []
    for item in unfolded:
        for place_id, weight in item.inputs:
            arcs.append(
                StructureArc(
                    id=f"a{len(arcs) + 1}", source=place_id, target=item.node.id, weight=weight
                )
            )
        for place_id, weight in item.outputs:
            arcs.append(
                StructureArc(
                    id=f"a{len(arcs) + 1}", source=item.node.id, target=place_id, weight=weight
                )
            )
    if len(arcs) > limits.max_arcs:
        raise UnfoldingTooLargeError(f"The unfolding has more than {limits.max_arcs} arcs")
    structure = NetStructure(
        net_id=net_id,
        kind="pt",
        places=tuple(table.nodes),
        transitions=tuple(item.node for item in unfolded),
        arcs=tuple(arcs),
        has_reference_nodes=False,
    )
    return Unfolded(
        document=structure_to_document(
            structure=structure, source_id=f"unfolding-of-{document.source_id}"
        ),
        mapping=UnfoldingMapping(
            places=tuple(table.mapping), transitions=tuple(item.mapping for item in unfolded)
        ),
    )
