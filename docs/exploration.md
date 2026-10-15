# Exploration: unconventional uses of an LLM next to model checkers

Status: research notes and hypotheses, **not** results. Nothing here has been run yet. Each
direction is a bet; the "minimal experiment" says how to find out cheaply whether it pays off.

## The organizing principle: where unsoundness is harmless

An LLM is unreliable as a judge, but that does not matter everywhere. Its output can be used
freely when something deterministic stands between it and the user:

| LLM output | Who judges it | What a wrong guess costs |
|---|---|---|
| A firing sequence "that probably violates P" | Replay on the net | Time only |
| A conjecture "P holds" | A model checker | Time only |
| An invariant / certificate | A checker of that certificate | Time only |
| A candidate lemma | A model checker, plus a deterministic composition check | Time only |
| A tricky net or formula | Comparison of several tools | Nothing, it is a test |
| A proposed repair | Model checker + regression suite | Time only |

The rule for every direction below: **the LLM may be wrong; it may never be the last word.**
Anything where the LLM's own judgement would reach the user as a verdict is out of scope
(see rule 1 of `CLAUDE.md`).

The usual direction (propose properties, verify them) uses only the second row. The rest of the
table is where the less explored ideas are.

---

## 1. Falsification-first: LLM-guided counterexample hunting

**Idea.** Ask the LLM for a firing sequence it suspects violates a property, using names and
structure ("what interleaving would break this lock?"). Replay it; if it violates the property,
it is a genuine counterexample, with no completeness or soundness question left.
**Why an LLM.** Humans find bugs by imagining adversarial schedules; the LLM can imitate that.
**Judge.** Replay (`POST /v1/nets/{id}/replay`).
**Minimal experiment.** On MCC instances where tools find a counterexample, compare the hit rate
of LLM-proposed sequences against random walks and against greedy heuristics at equal budget.
**Risk.** On large nets the sequence may be too long to produce; may only help on small/medium
instances or as a seed for guided search.

## 2. Conjecture-refutation loop (the refutations are the product)

**Idea.** The LLM proposes bold conjectures ("process 2 can never starve", "the buffer never
holds more than 3 items"); tools try to refute them; the refuted ones feed back as new knowledge.
Report not only what is true but the **surprising false beliefs**: conjectures that looked
plausible from the names and description but fail. Those often point at modeling errors.
**Judge.** Model checker.
**Minimal experiment.** On mutated MCC models, check whether the false-but-plausible conjectures
of the original vs mutated net localize the injected fault.
**Risk.** Many refuted conjectures are noise; needs ranking by how plausible they were.

## 3. Certificate synthesis for hard properties

**Idea.** For properties where tools time out (unbounded or large nets), the LLM proposes
helper invariants (linear invariants over places, trap/siphon-based, strengthenings of the
property). Checking a candidate invariant is cheap and sound; a good one can make the original
problem easy for SMT- or induction-based engines.
**Judge.** Invariant checking (inductiveness check), then the usual engine with the invariant
added.
**Minimal experiment.** Take MCC reachability instances that smpt or ITS-Tools leave unsolved;
measure how many become solvable when given LLM-suggested invariants, and compare with invariants
computed by the structural analysis alone.
**Risk.** Structural analysis may already give everything the LLM would; the experiment measures
exactly that. Count only the *extra* instances solved.

## 4. Lemma decomposition when the answer is UNKNOWN

**Idea.** On TIMEOUT/UNKNOWN, the LLM splits the property into lemmas and assumptions
(assume-guarantee style), each cheaper to check.
**Judge.** Model checker per lemma; the composition (do the lemmas imply the goal?) is checked
by a deterministic procedure, never by LLM argument.
**Minimal experiment.** Properties over product-like nets (several components) with a known
decomposition; success = proof assembled and checked.
**Risk.** Circular assumptions. The composition checker must reject circular reasoning.

## 5. Adversarial and metamorphic testing of the tools themselves

**Idea.** The LLM invents nets and formulas aimed at semantic corner cases (neXt, weighted arcs,
self-loops, zero initial marking, deadlock conventions, empty pre/post sets), and metamorphic
relations whose verdict must not change: renaming places, adding an unobserved place, splitting
a transition, reordering arcs, applying a reduction declared property-preserving.
**Judge.** Disagreement between equivalent tools, or between a net and its transformed version.
**Minimal experiment.** Run it across the integrated engines; count real discrepancies after
triage. Any confirmed bug is a publishable by-product and useful feedback for tool authors.
**Risk.** Needs the engines and the equivalence table first; many "discrepancies" will be
semantic differences to document, not bugs.

## 6. Description-versus-net discrepancy detection

**Idea.** From the textual description of a system, the LLM states what must hold, then checks
that the net agrees; in the other direction, it describes the behavior it observes from
simulations and the description is compared with the intended one. Disagreement flags a modeling
error or an ambiguous description.
**Judge.** Model checker for the stated expectations; a human for ambiguities.
**Minimal experiment.** Inject faults into models that come with a description; measure
detection rate with and without the description.
**Risk.** MCC models are presumably correct, so measure on mutants; descriptions can be vague.

## 7. Bug-pattern transfer from outside Petri nets

**Idea.** A catalog of concurrency pathologies (lost wakeup, circular wait, priority inversion,
ABA-like reuse, starvation, missing release, double acquire) that the LLM recognizes in net
fragments from names and structure, then instantiates as formulas.
**Judge.** Model checker.
**Minimal experiment.** Compare property sets generated with and without the catalog on mutants
that inject exactly those pathologies.
**Risk.** Pattern recognition from names fails on unnamed or generated nets.

## 8. Counterexample-driven model repair

**Idea.** From a counterexample, the LLM proposes a minimal edit (add an arc, change a weight,
change the initial marking). The repair is accepted only if the property now holds **and** a
regression suite of previously proven properties still holds; minimality is measured by edit
distance.
**Judge.** Model checker on the repaired net.
**Minimal experiment.** Mutants of known-good models: does the proposed repair restore the
original behavior (or an equivalent one)?
**Risk.** Repairs that satisfy the property trivially (e.g. disable the behavior). The regression
suite and a "liveness preserved" check guard against that.

## 9. Benchmark synthesis: nets designed to separate tools

**Idea.** The LLM generates scalable model families deliberately hard for one tool and easy for
another, using what the capability and results data say about tool weaknesses. Useful as training
data for the tool selector and as candidate MCC submissions.
**Judge.** Actual tool runs.
**Minimal experiment.** Generate families; measure the separation they achieve (time ratio
between best and worst tool) against existing MCC families.
**Risk.** Synthetic families may be unrepresentative of real models; label them as such.

## 10. What-if exploration in natural language

**Idea.** "What changes if the buffer has capacity 2?" becomes a net mutation, plus a diff of the
set of verified properties between the original and the variant.
**Judge.** Model checker on both versions.
**Minimal experiment.** Compare to hand-written mutations on a few models; check that the LLM's
natural-language summary of the diff matches the tool output.
**Risk.** Summaries drifting from the actual diff; always show the machine-readable diff next to
the explanation.

---

## Suggested order

1. **Replay and falsification (1)** and **metamorphic testing (5)**: cheapest, need only replay
   and two engines, and produce checkable facts quickly.
2. **Conjecture-refutation (2)** and **certificates (3)**: the most distinctive; (3) has a clean
   measurable question (extra instances solved).
3. The rest once the selector and mutation evaluation exist.

## Ground rules for all experiments

- Pre-register the metric and the baseline before running (including "structural analysis alone"
  and "random/greedy search" baselines).
- Record negative results in `bench/experiments/` with versions of tools and LLM.
- Evaluate by model family, with unpublished models where possible (contamination).
- Never merge an exploratory feature into the default path without a measured gain over the
  baseline.
