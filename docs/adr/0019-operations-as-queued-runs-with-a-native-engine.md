# 19. Operations run as queued runs, cached by key, on a native engine

Status: accepted

## Context
ADR 0014 gives every analysis and reduction its own endpoint and asks for one generic runner.
Several questions were open: where the platform's own analyses run (the platform must not run
engines on the host, ADR 0004), how a quick operation answers `200` and a slow one `202`, how
results are cached, and how adding an operation stays a one-place change.

## Decision
1. **An operation is defined once** (`app/domain/operations.py`, `OperationDefinition`): name,
   kind, parameters model, result model and the pure function that computes it. Its route, its
   entry in the catalog and the engine that runs it are derived from that definition. Adding an
   analysis is one module in `app/domain/analyses/`, one line in its catalog, and a known answer in
   the contract test.
2. **The platform's own analyses run in a container**, the `native` engine (`engines/native`),
   like any other engine: same limits, same timeout and kill, same envelope. The image holds
   `app.domain`, and its adapter calls the definition's function; the algorithms are unit-tested as
   plain functions, and a Docker test checks that the container gives the same answer. Other tools
   (Tina, a reducer) join by declaring the operation in the registry (`EngineSpec.operations`).
3. **A run is a row of a queue**, like a check (ADR 0018): `operation_runs`, claimed by one
   conditional update, kept alive by a lease, recovered when its owner died. The request waits
   up to `PNVERIF_OPERATION_WAIT_SECONDS` for the run to finish and answers `200`; otherwise it
   answers `202` with the run to follow at `GET /v1/runs/{id}` (cancel with `DELETE`).
4. **A finished run is the cache.** The key is the hash of net, operation, parameters, engine and
   the engine's pinned version, with a unique index over the queued, running and done runs: asking
   again returns the run that exists, also across restarts and processes. Limits are not in the
   key (a result is the same under any limit that let it finish). A failed, cancelled or
   interrupted run frees the key. Changing an algorithm means bumping the native engine's version
   (registry and Dockerfile), which invalidates its cache.
5. **An engine's result is checked like a verdict** (`operation_check`): it must have the
   operation's result shape, and every element it cites must exist in the net, of that kind and
   with that name. Otherwise the run fails with the reason; nothing wrong is stored as a result.
6. **Failures are in the envelope**, not HTTP errors (docs/json-contract.md): a run that failed
   answers `200` with `status: failed` and an `error`.

## Consequences
- The synchronous path and the queue are one mechanism; there is no second way to run an operation.
- Every analysis pays a container start. That is the price of one isolation story; fast paths can
  come later as a cache-first policy, not as a second runner.
- Results can be shared between nets only by net identity (ADR 0015), never by similarity.
