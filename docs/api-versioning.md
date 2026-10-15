# API compatibility policy

The API lives under `/v1`. This page says what may change inside a major version and how a
breaking change is made.

## What is the contract
- The routes, methods and status codes under `/v1`, and the JSON they accept and return, as
  described by the committed OpenAPI document (`docs/openapi.json`) and the JSON Schemas
  (`docs/schemas/`). Both are checked against the code by hooks and CI.
- The event vocabulary of sessions (ADR 0008) and the engine contract (`docs/engine-contract.md`).
- The identity of a net (ADR 0015): the same net keeps its id across versions.

## Allowed inside `/v1` (compatible)
Adding a route, an optional request field, a response field, an enum value in a response that
clients treat as open, an event kind (clients ignore kinds they do not know), a tool or an engine.
Clients must ignore response fields they do not know.

## Breaking (needs `/v2`)
Removing or renaming a route, a field or an event kind; making an optional field required; changing
a type, a status code or the meaning of a value; changing how a net id is computed; narrowing what
a route accepts.

## How a breaking change is made
1. An ADR explains why.
2. The new behaviour is added under `/v2`; `/v1` keeps working unchanged.
3. `/v1` responses carry `Deprecation` and `Sunset` headers once a date is set, and the release
   notes announce it. `/v1` is removed no sooner than six months after that announcement.
4. Stored data is migrated by numbered migrations (`docs/architecture.md`), never edited in place
   by hand; an identity change creates new nets and records the old id.

## Versions you can see
`schema_version` in the result envelope and in net documents changes only with an incompatible
shape. The software version (`GET /openapi.json`, `info.version`) follows `docs/releasing.md`.
