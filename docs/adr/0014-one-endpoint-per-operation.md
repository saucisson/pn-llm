# 14. One endpoint per operation, independent of the tool

Status: proposed (review before any code)

## Context
Analyses and transformations (reductions, unfolding) were grouped in multi-purpose endpoints
(`structure`, `reductions` with a list of rules). A grouped endpoint hides what was computed, mixes
result shapes, makes caching and testing coarse, and gives the LLM vague tools. Also, an endpoint
named after a tool would tie clients to one implementation, while several tools can compute the
same thing (tool selection, milestone M5).

## Decision
1. **Each analysis and each transformation has its own endpoint and does exactly one thing**: one
   type of analysis (for example P-invariants) or one reduction rule (for example fusion of series
   places). Never a bundle, never a list of operations in a request body.
2. **The endpoint is the operation, not the tool.** `POST /v1/nets/{net_id}/analyses/p-invariants`
   can be served by any engine that declares that operation. The request has an `engine` field
   (`auto` by default, letting tool selection choose among equivalent tools); the result envelope
   says which tool and version computed it (`docs/json-contract.md`).
3. **One route, one request model, one result model per operation.** Shared mechanics (job and
   lease, caching, envelope, engine dispatch, limits) live in one generic runner that every
   operation reuses; operations never share a result shape just to share code.
4. **Composition belongs to the caller.** Reducing a net with several rules, or running several
   analyses, is several calls, decided by the client or by the LLM, who sees each result. The
   platform offers no "reduce with everything" or "analyse everything" endpoint. A catalog
   endpoint lists the operations, their parameters and, for a reduction, the properties it
   preserves.
5. **Reductions protect what is observed.** A reduction request lists the elements to protect
   (those cited by formulas); the rule never removes or merges them (`CLAUDE.md` domain rule 3).
   A reduction that applies creates a new net linked to its parent (ADR 0005) and returns the
   mapping of elements; one that does not apply returns `changed: false` and creates nothing.
6. **Adding an operation** means a route, a request model, a result model, a use case, an entry in
   the catalog and an engine declaring it (`operations`), with a test using a net with a known
   answer. No other file changes.
7. Verification of formulas (`checks`) is not an analysis or a transformation and keeps its own
   endpoint, batch semantics and job lifecycle (ADR 0003).

## Consequences
- Tools offered to the LLM are precise and small, results are comparable across engines, and
  caching and evaluation are per operation.
- More routes and models to maintain; the generic runner and the catalog keep that cost low.
- The engine registry maps operations to capable engines, which is the basis for tool selection.
