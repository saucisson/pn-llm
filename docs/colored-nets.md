# Colored nets

What the platform does with a colored (symmetric) net, what it leaves to engines, and what is not
done yet. The net itself is the canonical document of `docs/net-document.md`; PNML round-trips.

## What is computed at the colored level
`GET /v1/nets/{id}/colored` and the tool `colored_summary` read the declarations and the terms of
a symmetric net into typed models (`app/domain/colored*.py`) and say, without unfolding anything:

- the **sorts** (enumerations, integer ranges, products, dot, aliases) and the number of values
  of each;
- **places grouped by domain**, **transitions grouped by the variables they use**, with the number
  of bindings each would have at most, and how many have a guard;
- the **color functions** on arcs (variable, constant, all, tuple, successor, predecessor, sum,
  difference, weighted);
- the **size of the unfolding**: exact for places (the sum of the domain sizes), an upper bound for
  transitions (guards can only remove bindings), an estimate for arcs.

The summary is bounded by the number of distinct sorts and variable signatures, plus a few named
examples per group, so it stays small whatever the size of the unfolding. A construct outside the
vocabulary (an operator declaration, a partition, a list or string sort...) is refused by its name,
never summarized wrongly.

## What is not computed on the colored net
Structural analyses (invariants, siphons, bounds, reductions) work on P/T nets: the native engine
refuses a colored net with a clear message. They will run on the unfolding once the platform can
unfold (below). Invariants, bounds and symmetries of the colored net itself are not computed.

## Verification
Engines that read colored PNML (`supports_colored` in the registry: Tapaal and ITS-Tools) check
formulas on the colored net with the place and transition names of the net. Tapaal unfolds the net
internally, so it gives no counterexample on a colored net (the names would not be the net's),
and says so in a warning.

## Not done yet (milestone M3)
Unfolding with a mapping from unfolded elements to colored ones, formulas per color or binding,
counterexamples with bindings, and the link between a colored contest model and its P/T version
are open (#53 to #57, #60).

## Unfolding

`unfold` (`app/domain/unfolding.py`) turns a symmetric net into the P/T net it stands for:

- a place over a sort of `n` values becomes `n` places, named `<place>_<color>` (a place over one
  value keeps its id); the initial marking is evaluated per color;
- a transition becomes one transition per assignment of the variables it uses (in its inscriptions
  and guard) that satisfies the guard and for which every inscription is defined; it is named
  `<transition>_<color of each variable, by variable name>`; a clash gets a `~n` suffix;
- an inscription (`n'x`, sums and differences of multisets, `all`, tuples, successor, predecessor)
  becomes arcs weighted by multiplicity; a successor past the end of a range or of a non-cyclic
  enumeration leaves that binding out, a subtraction below zero is refused;
- colors are named as in the net: constants by name, numbers as such, tuples with their parts joined
  by dots (`1.a`).

The mapping lists every unfolded place with its colored place and color, and every unfolded
transition with its colored transition and binding. The unfolding is bounded by `UnfoldLimits`
(places, transitions, arcs; one transition with more bindings than the limit is refused at once) and
reports an `UnfoldingTooLargeError` instead of exhausting memory. The contest's
`Philosophers-COL-000100` unfolds to 500 places and 500 transitions, the size of
`Philosophers-PT-000100`.

The unfolding is the operation `unfold` (`POST /v1/nets/{id}/reductions/unfold`, body
`{"parameters": {"max_places": ..., "max_transitions": ..., "max_arcs": ...}}`). Like any reduction
it runs in the `native` engine, stores the unfolded P/T net linked to its parent (`parent_id`,
`reductions_applied: ["unfold"]`) and answers with `new_net_id` and the mapping. A P/T net, or an
unfolding over the limits, is a failed run with the reason in `error.message`.
