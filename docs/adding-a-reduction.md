# Adding a reduction rule

A reduction rule rewrites a P/T net into a smaller one that keeps some behaviour. Each rule is one
operation (ADR 0014, ADR 0019): a module in `api/app/domain/reductions/`, one entry in
`REDUCTIONS`, and nothing else.

## What a rule is

A rule is a function `rule(*, net, protected) -> Step | None` that rewrites a private
`WorkingNet` once, somewhere it applies, and says what it did (`Step`: removed ids, merges,
expansions). `reduce_with` (`driver.py`) calls it until it returns `None` or `max_applications`
is reached, and builds the answer. The public function of the rule is three lines: it names the
rule, gives what it preserves, and calls `reduce_with`.

## Rules every rule follows

1. **Protected elements are untouched** (CLAUDE.md, domain rule 3). A rule never removes or
   merges an id in `protected`; it may keep one of two twins because it is protected. A rule
   that changes how tokens flow through an element (fusing a place into its neighbour, merging
   two transitions into one) must also leave the elements around it alone when they are protected,
   because a formula about a neighbour sees the difference. Say in the rule's docstring which
   elements it needs unprotected.
2. **Say what is preserved**, with the words of this vocabulary, in `preserves`:
   `reachability` (the markings of the kept places that can be reached are the same),
   `deadlock_freedom`, `liveness`, `boundedness`, `ltl` (runs of kept places, including with
   neXt), `ltl_without_next` (as `ltl`, but a step may disappear: not for a formula using X).
   A rule claims only what it has been checked to preserve.
3. **Never claim more than the conditions give.** A rule written from a paper cites the paper in
   its docstring and states the conditions it checks, not the ones it hopes for.
4. **Nothing applicable is an answer.** `changed: false` creates no net.
5. **Expansions for lifting.** If a firing of a transition of the reduced net stands for a
   sequence of the parent (a fused transition, a transition that now also performs a removed
   one), return it in `Step.expansions`, so traces found on the reduced net can be lifted to the
   original (`TransitionExpansion`).

## The test every rule must pass

`api/tests/unit/test_reductions.py` runs every rule of the catalog on 300 random small nets with
random protected elements and compares the state spaces: the markings of the kept places that
are reachable, and the existence of a deadlock, must be the same whenever the rule says it
preserves them; protected ids must not be removed or merged. A rule added to `REDUCTIONS` is
tested by this loop without writing anything; add known small examples next to it (one where the
rule applies, one where it does not, one with a protected element).

## Version

The reductions run in the `native` engine: when a rule changes, bump its version (registry,
Dockerfile, compose, `docs/engines.md`) and update `engines/native/DIGEST`
(`python3 scripts/native_digest.py --write`); a test fails until you do.
