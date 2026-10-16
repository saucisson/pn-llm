# Capabilities, equivalence and selection of engines

## Classes of properties
A formula belongs to a *class*: its logic (`state`, `ctl`, `ltl`), what its atoms count
(`cardinality` of places, `fireability` of transitions, `mixed`, or `none` for a bare deadlock
question) and whether it uses neXt (`+next`, LTL `X` or CTL `AX`/`EX`: sensitive to stuttering, so
some reductions are not allowed, CLAUDE.md domain rule 3). The key is `logic-atoms[+next]`, such as
`ltl-fireability+next`.

## Capabilities
An engine declares the contest examinations it takes part in (`docs/mcc-tools.md`). It *can check*
a class when it takes part in every examination the class needs: `ReachabilityCardinality`,
`CTLFireability`, ... for one kind of atom, both categories for `mixed`, either for `none`.
`GET /v1/engines` lists the engines with their examinations, classes and limitations and filters
with `?can_check=<class>&colored=<bool>`; `GET /v1/engines/capabilities` gives, per class, the engines
that check it and those that also read colored nets.

## Equivalence
Two engines are **equivalent for a class** when both can check it (same questions, same verdict
domain: TRUE, FALSE, UNKNOWN, TIMEOUT, OOM, ERROR) and no known difference of meaning separates them.
A difference that cannot change a verdict is a **caveat** (an atom rewritten into an equivalent one,
no counterexample); one that can change it **breaks** the equivalence for the classes it names, and
the engine leaves the class. `GET /v1/engines/equivalence` is the table the selector uses. A
difference is added when it is observed (the conformance suite, `docs/conformance-report.md`, is
where it shows), not when it is feared; today none breaks an equivalence. Equivalence is about
meaning: it says nothing about speed.

## Selection
`POST /v1/select-tools` takes a net, formulas and limits and returns the candidate engines, best
first. A candidate is available, can check every class of the formulas and reads the kind of net.
They are ranked by the share of contest runs that computed an answer on the examinations the
formulas need (ties by median time), from the results imported by `python -m app.seed --results-only`;
the contest's reference rows are not engines and do not count. Without imported results the order is
fixed and no probability is invented (`basis: preference`). The ranking never overrides a
capability. A learned predictor (milestone M5) replaces the history by features of the net and the
formula; the endpoint does not change.

## Portfolios and contradictions
`engine: auto` with `portfolio: k` (at most 4) runs the `k` best equivalent engines at the same time.
Unless `cross_check` is set, the engines still running are stopped as soon as every formula has a
definitive verdict from one of them; with `cross_check` the platform waits for all of them and
compares. Every engine's answer is kept in `alternatives` (engine, version, verdict, time, warnings,
whether it gave a trace).

If definitive verdicts disagree the result is `UNKNOWN` with `agreement: contradiction`, the
warning `engines_contradict` and all the evidence: the platform does not choose a side (CLAUDE.md,
domain rule 8). The one exception is a counterexample the platform can replay itself: a FALSE for an
invariant (`AG phi`, `G phi`, with `phi` free of temporal operators) whose trace, replayed on the
net, really ends in a marking that breaks `phi` is settled by the net (`arbitration:
counterexample_replayed`); the contradiction stays reported, because one engine was wrong.
