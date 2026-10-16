from pathlib import Path

import pytest

from app.domain.colored import (
    EnumerationSort,
    ProductSort,
    UnsupportedColoredError,
    read_declarations,
    sort_size,
)
from app.domain.colored_summary import summarize_colored
from app.domain.colored_terms import (
    AllTerm,
    Comparison,
    Junction,
    Negation,
    NumberOfTerm,
    SubtractTerm,
    SuccessorTerm,
    TupleTerm,
    VariableTerm,
    read_annotation_guard,
    read_annotation_term,
)
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml
from tests.support import MUTEX_DOCUMENT

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
MODELS = {
    "database": CORPUS / "colored" / "DatabaseWithMutex-COL-02.pnml",
    "philosophers": CORPUS / "colored" / "Philosophers-COL-000100.pnml",
    "filesystem": CORPUS / "colored" / "FileSystem-COL-N02I10B08.pnml",
    "pgcd": CORPUS / "mcc" / "PGCD-COL-D04N050" / "model.pnml",
    "guarded": CORPUS / "colored" / "guarded.pnml",
}


def load(name):
    return import_pnml(payload=MODELS[name].read_bytes(), limits=DocumentLimits())


def terms_of(document):
    """Every inscription, marking and guard of a document, read."""
    for located in document.located_containers():
        container = located.container
        yield from (read_annotation_term(annotation=a.inscription) for a in container.arcs)
        yield from (read_annotation_term(annotation=p.initial_marking) for p in container.places)
        yield from (read_annotation_guard(annotation=t.condition) for t in container.transitions)


def test_sorts_and_variables_are_read_with_their_sizes():
    declarations = read_declarations(document=load("database"))
    by_name = {s.name: s for s in declarations.sorts}
    assert isinstance(by_name["site"], EnumerationSort)
    assert by_name["site"].cyclic
    assert isinstance(by_name["SF"], ProductSort)
    assert sort_size(declarations=declarations, sort_id="sf") == 4  # 2 sites x 2 files
    assert {v.name: v.sort for v in declarations.variables} == {"s": "site", "f": "file"}


def test_every_term_and_guard_of_the_fixtures_is_understood():
    for name in MODELS:
        assert sum(1 for _ in terms_of(load(name))) > 4, name


def test_terms_have_their_typed_shape():
    document = load("database")
    arc = next(a for a in document.pages[0].arcs if a.id == "arc35")
    term = read_annotation_term(annotation=arc.inscription)
    assert isinstance(term, SubtractTerm)
    assert isinstance(term.left.arguments[0], NumberOfTerm)
    assert isinstance(term.left.arguments[0].item, TupleTerm)
    assert any(isinstance(item, VariableTerm) for item in term.left.arguments[0].item.items)
    initial = read_annotation_term(annotation=load("pgcd").pages[0].places[0].initial_marking)
    assert isinstance(initial, NumberOfTerm)
    assert isinstance(initial.item, AllTerm)


def test_guards_are_read_as_trees_and_successors_in_arcs_too():
    guard = read_annotation_guard(annotation=load("guarded").pages[0].transitions[0].condition)
    assert isinstance(guard, Junction)
    assert guard.operator == "and"
    comparison, negation = guard.arguments
    assert isinstance(comparison, Comparison)
    assert comparison.operator == "!="
    assert isinstance(negation, Negation)
    assert negation.argument.operator == "<"
    assert isinstance(negation.argument.right, SuccessorTerm)
    assert any(isinstance(t, SuccessorTerm) for t in _all_subterms(load("pgcd")))


def _all_subterms(document):
    pending = [t for t in terms_of(document) if t is not None and not isinstance(t, Comparison)]
    while pending:
        term = pending.pop()
        yield term
        for field in ("items", "arguments"):
            pending.extend(getattr(term, field, ()))
        for field in ("argument", "item", "left", "right"):
            inner = getattr(term, field, None)
            if inner is not None and hasattr(inner, "kind"):
                pending.append(inner)


def test_the_database_summary_says_what_unfolding_would_cost():
    summary = summarize_colored(document=load("database"))
    assert [(s.name, s.size) for s in summary.sorts] == [("site", 2), ("file", 2), ("SF", 4)]
    assert summary.sorts[0].detail.startswith("cyclic enumeration: 1, 2")
    assert summary.sorts[2].detail == "site x file"
    assert {(g.sort, g.count) for g in summary.place_groups} == {
        ("SF", 8),
        ("site", 2),
        ("file", 1),
    }
    assert summary.unfolded.places == 8 * 4 + 2 * 2 + 1 * 2
    assert summary.unfolded.transitions_upper_bound == 32
    assert any(f.function == "difference" for f in summary.arc_functions)


def test_philosophers_unfold_to_five_places_per_philosopher():
    summary = summarize_colored(document=load("philosophers"))
    assert summary.unfolded.places == 5 * 100
    assert [(g.sort, g.domain_size, g.count) for g in summary.place_groups] == [("Philo", 100, 5)]
    group = summary.transition_groups[0]
    assert group.bindings_upper_bound == 100
    assert len(group.examples) <= 3
    assert all(e.kind == "transition" for e in group.examples)


def test_a_model_with_a_doubly_wrapped_subterm_and_the_dot_sort_is_summarized():
    summary = summarize_colored(document=load("filesystem"))
    assert any(g.sort == "dot" for g in summary.place_groups)
    assert {s.name for s in summary.sorts} >= {"INODE", "BLOCK", "Bool"}


def test_guards_and_variables_decide_the_number_of_bindings_and_are_counted_per_group():
    summary = summarize_colored(document=load("guarded"))
    (group,) = summary.transition_groups
    assert group.variables == ("x: C", "y: C")
    assert (group.count, group.with_guard, group.bindings_upper_bound) == (1, 1, 9)
    assert {f.function: f.count for f in summary.arc_functions} == {
        "sum": 1,
        "variable": 2,
        "weighted": 1,
    }
    assert summary.unfolded.places == 6
    assert summary.unfolded.transitions_upper_bound == 9


def test_a_net_that_is_not_symmetric_is_refused():
    with pytest.raises(UnsupportedColoredError, match="symmetric"):
        summarize_colored(document=MUTEX_DOCUMENT)


def test_an_unsupported_construct_is_refused_by_name_not_misread():
    text = (
        MODELS["database"]
        .read_text()
        .replace("<cyclicenumeration>", '<finiteintrange start="1" end="2"/><cyclicenumeration>', 1)
    )
    document = import_pnml(payload=text.encode(), limits=DocumentLimits())
    with pytest.raises(UnsupportedColoredError):
        read_declarations(document=document)
    mangled = (
        MODELS["database"]
        .read_text()
        .replace("<productsort>", "<partition>", 1)
        .replace("</productsort>", "</partition>", 1)
    )
    with pytest.raises(UnsupportedColoredError, match="partition"):
        read_declarations(document=import_pnml(payload=mangled.encode(), limits=DocumentLimits()))
    undeclared = (
        MODELS["database"].read_text().replace('declaration="site"', 'declaration="nowhere"', 1)
    )
    with pytest.raises(UnsupportedColoredError, match="nowhere"):
        summarize_colored(
            document=import_pnml(payload=undeclared.encode(), limits=DocumentLimits())
        )
