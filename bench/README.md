# bench

Evaluation scripts and conditions (protocol: `docs/evaluation.md`, ADR 0012).

## B0: the rule-based baseline

`app/domain/baseline.py` (`baseline_properties`) is the condition B0: the standard properties
an engineer tries first, written from the structure of a P/T net and the static analyses, with no
language model. It is deterministic and returns the same `Formula` objects as the other conditions
(origin `template`), so engines, replay, triviality filters and measures apply unchanged.

| Family | Property | Needs |
|---|---|---|
| deadlock freedom | `AG !deadlock` | nothing |
| exclusion | `AG !(p >= 1 && q >= 1)` for two places of a P-invariant worth one token | P-invariants |
| boundedness | `AG p <= k`, k the structural bound, else 1 (or the initial marking if larger) | place bounds (optional) |
| quasi-liveness | `EF fireable(t)` for each transition | nothing |
| home state | `AG EF (initial marking)` | at most 40 places |

Budget parity: the generator returns at most `max_properties` properties, deadlock freedom first
and then the families in turns, so a small budget still covers each family. Properties that the
structure alone decides (a bound given by an invariant) are kept on purpose: the non-triviality
measure (M4) is expected to count them against B0.

Status: the generator exists and is tested; review by a second person is pending.

## M1: soundness audit

`python -m app.audit_sessions [--session ID ...]` checks every verdict event of the stored session
logs against the stored jobs. It exits 1 and lists a finding when a verdict has no finished job or
result behind it, or differs from the engine's verdict, formula, engine or version, or disagrees on
the counterexample; an UNKNOWN, TIMEOUT, OOM or ERROR in the job cannot appear as another verdict.
Contradictions between engines found in the jobs are listed, never resolved. Run it on every set of
sessions before reporting a result: any finding is a defect to fix, not a number to optimise.

## M4: non-triviality

`non_triviality_by_condition` (`app/domain/non_triviality.py`) counts, per condition, the properties
whose premise is impossible (`vacuous_antecedent`) and those the structure decides
(`holds_in_every_state`, `holds_in_no_state`: bounds, invariants, dead transitions). The findings
come from `triviality_of`, the filter the assistant sees in `check_formulas`; it is not redone
here. Counts are pooled per family, the condition is the mean over families, and a family without
any property is listed without a share instead of counting as 0 or 1.

## M5 and M6: mutants

`app/domain/mutation.py` injects one fault per mutant (arc removed or added, weight or initial
marking changed, transition removed) into a P/T net, chosen from a seed so every condition is judged
on the same mutants. `app/domain/mutation_score.py` judges them: a property kills a mutant when its
verdict on the mutant differs from its verdict on the original, both being TRUE or FALSE. A
timeout, out-of-memory, UNKNOWN or error never kills and never clears: such a mutant is
*undecided* and counted apart; a mutant every property decided without a change *survived*, and is
not called equivalent. M5 is killed over killed plus survived; M6 counts a fault as found when a
property true on the original fails on the mutant with a counterexample that replays there.
Families are aggregated first, then conditions are averaged over families.

Status: operators and judging are in place; running the properties on the mutants through the
engines (same budget as every condition) belongs to the runner.

## Condition N: obfuscated names

`obfuscate_names` (`app/domain/obfuscation.py`) renames the places `p1..`, the transitions `t1..`
(sorted by original id, so the same net always gives the same renaming), the arcs and the pages,
and drops every name, graphic and tool-specific datum, including the names of the net and its pages.
The model sees only this net; `restore_formula` writes the properties it proposes back with the
original ids before the engines judge them, so results are comparable with the other conditions.
Colored nets are refused (their declarations would need renaming).

## Runner

`ExperimentRunner` (`app/application/experiment.py`) is the judge every condition goes through:
the properties (cut to the budget, in the order proposed) are checked by the engines on the net,
filtered for triviality, then checked on the mutants chosen from the seed and judged (M3 to M6).
A property a mutant cannot express (it lost an element the property cites) is an ERROR for it, so
the mutant stays undecided. Each `RunRecord` holds the condition, family, repetition, seed,
budget, git commit, the engines and versions that answered, and, for a model, its id and prompt
hash.

```bash
python -m app.run_experiment --split v1 --role dev --repetitions 5      # B0 on the dev families
```

The net of a family is its first stored P/T instance by name. The test families are refused unless
`--frozen TAG` names the frozen version.

### Model conditions

`--condition L1|L2|L3|N` lets the model work in a session (`ModelConditionRunner`) with the same
system prompt and budgets for all. L1 is given inspection and checks only (no analysis tools, no
structural verdict on checked properties, no engine choice); L2 all tools; L3 also the description
stored for the net (a family without one is skipped); N is L2 on the obfuscated net, the properties
being written back in original names before judging. Every question is answered with the same
"no answer is available" and counted. The properties are taken from the session events, duplicates
removed, renumbered `L2-1`.. and cut to the budget; the record keeps the session id (replayable),
the model id (`PNVERIF_ANTHROPIC_MODEL`, or the provider name) and the prompt hash (system prompt
and tools).

## Analysis

```bash
python -m app.run_experiment --split v1 --condition L3 --repetitions 5 > l3.jsonl
python -m app.analyze_runs b0.jsonl l1.jsonl l2.jsonl l3.jsonl n.jsonl > analysis.json
```

`app/domain/analysis_stats.py` averages each measure inside a family (repetitions first), then
compares conditions by the paired difference per family: mean, a seeded percentile bootstrap
interval over families (10,000 resamples), a bootstrap p-value. The primary outcome is M6 of L3
minus M6 of B0; the secondary comparisons (L3 against L2, L2 against L1, N against L2, and L3
against B0 on the other measures) are corrected with Holm's method. A family missing for one of two
conditions is excluded from that comparison and named in `excluded`. The script is identical on dev
and test. The decision thresholds are applied when the report is written (`docs/evaluation.md`).

## M8: blind expert rating

```bash
python -m app.rate sheet b0.jsonl l1.jsonl l2.jsonl l3.jsonl n.jsonl --per-family 10 \
  --items-out sheet.json --key-out key.json
# raters fill a list of {item_id, rater, score (1-5), keep (true/false)} each, in their own file
python -m app.rate analyze --key key.json ratings.json
```

The sheet shows each property in one canonical text form, without its gloss, with an opaque item id,
in an order shuffled from the seed; a property written identically by two conditions is rated once
and the rating counts for each. The key (item to conditions) stays with the analyst. At least two
raters rate every item; `analyze` prints Cohen's kappa for keep/drop and a linearly weighted kappa
for the 1 to 5 score, per pair of raters, and the per-condition per-family values (`M8_rating`,
`M8_keep`) that `app.analyze_runs`' comparison takes. Blinding is limited by the properties
themselves: the baseline's property shapes are recognizable to an expert, which the report must say.
