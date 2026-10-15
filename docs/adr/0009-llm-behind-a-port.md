# 9. The LLM is an outbound port with a scripted fake

Status: proposed (review before any code)

## Context
The agent loop must be testable without network, cost or randomness, and the LLM provider must be
replaceable. The text of a net (names of places and transitions) goes into prompts and is
attacker-controlled data.

## Decision
- `LlmGateway` is a port in `application/ports.py`: given the conversation so far and the tool
  specifications, it returns the next assistant step (text and/or tool calls). The provider
  adapter lives in `infrastructure/`; the provider SDK is imported nowhere else.
- The tools offered to the LLM are the use cases of `docs/json-contract.md` (net inspection,
  static analysis, reductions, checks, replay): structured JSON in and out, and **never the net
  itself** in PNML, XML or JSON (ADR 0013, ADR 0015). The agent has no capability the API does not already expose.
- Tests use a **scripted fake gateway** (a small class returning prepared steps). The real
  quality of the agent is measured in `bench/`, not in unit tests.
- Every run has budgets (steps, tool calls, tokens, wall time) set in `Settings`; exceeding one
  produces a `budget_exhausted` event, never a silent stop.
- Net content and user descriptions (ADR 0011) are data: it is quoted in clearly delimited blocks, tools cannot do anything
  irreversible, and tool arguments are validated like any API request. API keys come from
  `Settings`, are never logged, and never appear in events.

## Consequences
- The agent loop is ordinary, deterministic application code.
- Swapping or adding a provider is a new adapter, without touching use cases.
