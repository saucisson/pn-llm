# 13. Structured JSON everywhere; the LLM never reads the net

Status: proposed (review before any code)

## Context
Nets arrive as PNML (and, by ADR 0015, also as JSON). Analyses, reductions and checks produced results of
varying shapes, and a raw PNML in a prompt is large, noisy and unsafe (ADR 0009). The LLM needs
facts about the net (its places, transitions, neighbours), not its XML.

## Decision
1. **JSON is the representation of everything.** The net has a canonical JSON document (ADR 0015)
   and PNML is an alternative serialization chosen by content negotiation and used for engines.
   Every other input and output (inspections, analyses, reductions, formulas, checks, traces,
   sessions) is JSON described by pydantic models.
2. **One shared contract** (`docs/json-contract.md`): a common result envelope, one reference type
   for places and transitions (`ElementRef`: id and name), one pagination scheme, one
   representation for markings, bounds, invariants, traces and formulas. A concept has one model,
   reused by every service.
3. **Formulas are structured**: a JSON syntax tree whose atoms cite places and transitions by id.
   The platform checks the ids against the net and renders each engine's own syntax inside the
   adapter. The LLM never writes engine-specific syntax. Formulas imported from the MCC are parsed
   into the tree when possible, otherwise kept as raw text and never offered to the LLM.
4. **Inspection tools** give the LLM everything it needs to know about a net without reading it:
   summary, paginated lists of places, transitions and arcs, details of an element, neighbourhoods,
   name search, families of indexed names, initial marking.
5. **The LLM never receives the net itself, as PNML, XML or the full JSON net document**, from any
   tool, prompt or log it can see. `GET /v1/nets/{id}` exists for humans and clients and is
   excluded from the tool list offered to the LLM.
   Reductions return JSON (new net id, mapping of elements, rules applied); the reduced PNML
   stays inside the platform.
6. **Engines follow the same contract**: `request.json` and `result.json` use the envelope and the
   shared models, traces are structured JSON (docs/engine-contract.md). Analyses and reductions are engine
   operations under the same container contract; one endpoint per operation (ADR 0014).
7. **Enforcement**: pydantic models are the single source; JSON Schemas are exported from them and
   a test fails when the committed schemas are stale; contract tests check that every tool result
   validates against its schema and carries the envelope; a guard test fails if a tool offered to
   the LLM can return a net document, PNML or XML.

## Consequences
- Tools are interchangeable and composable, results are comparable across engines, and sessions are
  auditable from their logs (evaluation, `docs/evaluation.md`).
- Large nets stay usable: lists are paginated and families of names are compressed, so the context
  stays small and truncation is always explicit.
- The current `NetSummary` carries full lists of names and the current formula model is plain text:
  both change (backlog, milestone M1). Until then `docs/engine-contract.md` describes the target.
- Names and ids inside JSON are still untrusted data (ADR 0009, ADR 0011).
