# 10. A text-only chat UI on a modern TypeScript stack

Status: proposed (review before any code)

## Context
The first user workflow is a conversation in text. Displaying the net graphically is wanted later
(milestone M9, deferred), so the front end must be a foundation that can host a graph view
without a rewrite.

## Decision
- **Stack**: TypeScript in strict mode, React and Vite, in `ui/`. Tests with Vitest and Testing
  Library. Lint and format with Biome (one tool). Node is needed to build the UI, not to run the
  API; the built files are served by the API under `/ui`.
- **Transport**: server-sent events for the event stream (resumable with `Last-Event-ID`, through
  a `fetch`-based client so that authentication headers remain possible) and plain `fetch` `POST`
  for commands. No WebSocket: the flow is one-way, and SSE keeps every connection stateless and
  servable by any API process (ADR 0003, ADR 0008).
- **Single source of truth for types**: TypeScript types are generated from the OpenAPI schema of
  the API (`openapi-typescript`), which comes from the pydantic models. Events are a discriminated
  union handled by exhaustive `switch` statements (the compiler rejects an unhandled kind).
- **Rules, adapted from `docs/conventions.md`**: functions take one object of named parameters;
  data types are `readonly`; no mutation of arguments or shared state; linear functions without
  artificial helpers; a doc comment on every exported item; English everywhere; no `any`, no
  non-null assertions. Biome and `tsc --noEmit --strict` enforce what they can; the rest is review.
- **Rendering safety**: event data is rendered as React text, never as raw HTML.
- **User inputs**: a start form takes the PNML file (upload or drag and drop), the description of
  the system (typed, or a `.txt`/`.md` file) and the goal; the net is registered and the session
  created in one request. The form shows what was understood (net name, number of places,
  transitions and arcs, from the summary) before the user confirms. Later messages can add
  information or files.
- **Starting a session**: a form takes the PNML file, a free-text description of the model and the
  goal. The UI uploads the net, then the description (stored by the API, ADR 0011), then creates
  the session. Descriptions can be reused: when a net already has some, the user can pick one.
- **Thin client**: the UI offers nothing the REST API does not, so the API stays the single
  contract.
- **Text only for now**: place and transition names appear as text; no graph code until M9.

## Consequences
- A Node toolchain (LTS, pinned in `.nvmrc`) joins the dev setup; hooks and CI gain a UI job.
- A richer front end for M9 is added to the same project (Cytoscape.js or React Flow).
- Generated types make a breaking API change fail the UI build instead of failing in production.
