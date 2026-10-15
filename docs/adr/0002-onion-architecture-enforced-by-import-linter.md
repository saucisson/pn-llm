# 2. Onion architecture, enforced by import-linter

Status: accepted

## Context
The project will grow in several directions (colored nets, many engines, tool selection, an LLM
agent). Without rules, dependencies tangle and every change gets expensive.

## Decision
Onion architecture: `domain` at the center, then `application` (use cases and ports), then an outer
ring of `api` and `infrastructure` (siblings), with `main` as the composition root. Dependencies
point inward only. The rules are import-linter contracts checked at every commit and in CI.

## Consequences
- Use cases can be tested with real objects and are independent of HTTP, SQL and Docker.
- Swapping SQLite or the engine runner touches one adapter and `main`.
- Slightly more files than a flat layout; accepted for the evolvability.
- Layers must not be skipped on the way out: the API never imports an adapter.
