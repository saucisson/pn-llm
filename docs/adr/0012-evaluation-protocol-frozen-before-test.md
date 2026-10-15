# 12. The evaluation protocol is frozen before the test run

Status: proposed (review before any experiment)

## Context
LLM systems are easy to tune until they look good. The claims of `docs/objective.md` are only
credible if the protocol, the baseline, the metrics and the thresholds are fixed before seeing
test results.

## Decision
- `docs/objective.md` and `docs/evaluation.md` define claims, conditions, measures and thresholds.
- Before the first test run, a git tag `eval-freeze-N` records the protocol, the test families,
  the thresholds and the code versions. Later changes are listed as deviations in the report.
- The judge is deterministic (engines, replay, mutation); human ratings are blind.
- A rule-based baseline (B0) is part of the study, with the same budget as the LLM conditions.
- Null and negative results are published in `bench/results/NEGATIVE.md`.

## Consequences
- Extra up-front work (baseline, mutation pipeline, dataset selection), in exchange for results
  that can be defended.
- The product backlog and the research backlog share the event logs of sessions (ADR 0008).
