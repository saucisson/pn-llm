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
