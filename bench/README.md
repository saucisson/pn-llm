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
