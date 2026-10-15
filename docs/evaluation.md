# Evaluation protocol

Goal and claims: `docs/objective.md`. This protocol is written before any result exists and is
frozen (git tag) before the test run. Changes after that are recorded as deviations.

## Principles
1. **A deterministic judge**: engines, replay of counterexamples and mutation decide; no LLM
   grades LLM output. Human raters are blind to the condition.
2. **Unit of analysis = model family**, not instance (instances of one family are correlated).
3. **Budget parity**: every condition, baseline included, gets the same limits (LLM tokens and
   calls, engine time per property, number of properties).
4. **Dev and test families are disjoint.** Prompts and heuristics are tuned on dev only. The test
   set is run once per frozen version.
5. **Everything is recorded**: model identifier, prompt hash, tool image versions, seeds, budgets,
   git commit. Sessions are stored as event logs (ADR 0008) and replayable.
6. **Negative and null results are logged** (`bench/results/NEGATIVE.md`), as in the exploration
   charter.

## Conditions
| Id | Description |
|---|---|
| B0 | **Rule-based generator, no LLM**: standard properties from structure (deadlock freedom, boundedness of each place, quasi-liveness of each transition, exclusion between places of a common invariant, home-state candidates). This is the baseline the LLM must beat. |
| L1 | LLM with the net summary and the names of places and transitions only. |
| L2 | L1 plus static-analysis facts (invariants, bounds, siblings, structural class, deadlock hints). |
| L3 | L2 plus the user's description (stored as in ADR 0011). |
| N | L2 with **names obfuscated** (`p1`, `t1`, ...): measures how much the LLM relies on the semantic signal in names. |

Questions asked by the assistant are answered, offline, with "no answer available" and counted;
interaction is evaluated separately in the user study.

## Data
- **Dev set**: MCC families chosen for diversity (size, structure class, domain).
- **Test set**: disjoint families, frozen. Target at least 20 P/T families; the actual number and
  selection rule are fixed in the freeze tag.
- **Contamination control**: MCC models are public. Add models absent from the LLM's likely
  training data (unpublished models from the authors' own work, the newest MCC "surprise" models,
  synthetic families) and report public and unpublished results separately.
- **Descriptions**: MCC forms (origin `mcc`) and, for a subset, descriptions written by people who
  did not see the properties.
- **Mutants**: per model, faults injected by operators (arc removed or added, weight changed,
  initial marking changed, transition removed). Mutants that no engine can distinguish from the
  original within the budget are reported as *undecided*, never counted as equivalent or killed.

## Measures
| Id | Measure | Judge |
|---|---|---|
| M1 | **Unsupported verdicts** (must be 0), tool disagreements on equivalent tools | automatic audit of session logs |
| M2 | **Fidelity**: share of audited formulas (syntax trees, ADR 0013) faithful to the assistant's plain-language gloss | two blind raters on a random sample; agreement reported (Cohen's kappa) |
| M3 | Pipeline rates: well-formed, accepted by the engine, decided (TRUE or FALSE rather than UNKNOWN, TIMEOUT, OOM) | automatic |
| M4 | **Non-triviality**: share of properties neither vacuous nor implied by invariants | automatic filters (M5 backlog) |
| M5 | **Mutation score**: share of non-equivalent decided mutants killed by at least one property of the set (a property kills a mutant when its verdict differs from the original's) | engines |
| M6 | **Seeded fault finding** (primary): share of seeded faults for which some property returns a counterexample that replays on the mutant | engines and replay |
| M7 | Coverage: share of places and transitions cited by at least one property; number of distinct property classes | automatic |
| M8 | **Expert relevance**: 1 to 5 rating and "would keep this property" (yes or no) | at least two blind domain experts, randomized order, conditions hidden |
| M9 | Cost: tokens, wall time, engine time | automatic |
| M10 | Interaction (user study): time to first useful verified property, questions asked, share judged useful, correct reading of UNKNOWN and TIMEOUT | users, observation |
| M11 | Tool selection: regret against the single best tool and the virtual best tool, cross-validated by family | benchmark |

## Primary outcome and thresholds
Primary outcome: **M6 of L3 minus M6 of B0**, paired by family.

Provisional thresholds, to be confirmed or changed (with the reason) in the freeze tag:

| Criterion | Threshold |
|---|---|
| C1 / M1 | 0 unsupported verdicts |
| C2 / M2 | at least 90 % faithful, lower bound of the 95 % interval at least 80 % |
| C3 / primary | difference of at least +10 points, 95 % interval over families excluding 0 |
| M4 | at least 80 % non-trivial |
| M8 | L3 rated higher than B0 by the experts, with its interval excluding 0 |

Secondary comparisons (C4: L3 against L2 against L1, and N against L2; M5, M7, M9) are reported
with effect sizes and intervals, with Holm correction when tested. M10 is descriptive.

## Procedure
1. Run each condition with 5 repetitions per model (the LLM is stochastic); report the spread.
2. Aggregate by family first, then across families. Report per-family results, not just means.
3. Intervals by bootstrap over families. Report how many families were excluded and why.
4. Keep the analysis script in `bench/` and run it unchanged on dev and on test.

## Threats to validity
- **Contamination** of public models: unpublished models, obfuscated names (N), separate reports.
- **Mutation is a proxy for relevance**: complemented by blind expert ratings (M8).
- **Judge errors**: engines can be wrong; cross-check equivalent tools and log disagreements (M1).
- **Rater bias**: blind, randomized, two raters, agreement reported.
- **Tuning on the test set**: prevented by the dev and test split and the freeze tag.
- **Baseline strength**: B0 is built seriously and reviewed; a weak baseline would make C3 vacuous.
- **Small user study**: results are descriptive, no generalization is claimed from it.
- **Model drift**: LLM versions are pinned; reruns on a newer model are a new experiment.

## Order of work
E0 harness and B0 baseline. E1 soundness suite (known-verdict tests, M1 audit). E2 mutation
pipeline. E3 dataset selection and freeze. E4 development on dev families. E5 test run (once).
E6 expert ratings. E7 user study. E8 report, including negative results.
