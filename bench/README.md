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
