# 6. Verdicts are never invented

Status: accepted

## Context
The system exists to give trustworthy answers. A timeout reported as FALSE would be worse than no
answer.

## Decision
Verdicts are TRUE, FALSE, UNKNOWN, TIMEOUT, OOM or ERROR. Only an engine can produce TRUE or FALSE.
Any failure of the engine, its container or its adapter is ERROR, TIMEOUT or OOM, never a verdict.
The LLM never produces a verdict; it proposes, engines decide.

## Consequences
Tests cover each failure path; adapters must follow the same rule (`docs/engine-contract.md`).
