# Architecture

An **onion architecture**: the domain is at the center and knows nothing of the rest; each ring
depends only on the rings inside it. This file is stored documentation: it is kept in sync with the
code by a hook (`scripts/check_architecture_doc.py`) and the dependency rules are checked at every
commit (`lint-imports`). Decisions and their reasons are in `docs/adr/`.

## The rings

```
            main  (composition root)
              |
   +----------+-----------+
   |                      |
  api                infrastructure        <- outer ring: talks to the outside world
 (HTTP)        (SQLite, Docker, engines)
   |                      |
   +----------+-----------+
              |
         application                       <- use cases + ports (protocols)
              |
           domain                          <- models, errors, net document and PNML conversion
```

`api` and `infrastructure` are siblings: neither imports the other. They meet only in `main`,
which builds the adapters, injects them into the use cases, and hands the use cases to the routes.

## Modules

| Module | Ring | Responsibility |
|---|---|---|
| `app/domain/models.py` | domain | Frozen pydantic models of all data (nets, formulas, jobs, results, engine output) |
| `app/domain/schemas.py` | domain | Deterministic JSON Schema rendering of the public models, committed in `docs/schemas/` (`make schemas`) |
| `app/domain/net_document.py` | domain | `NetDocument`, the canonical JSON model of a net: pages, nodes, arcs, annotations, graphics, tool-specific data, `XmlNode` |
| `app/domain/canonical.py` | domain | Canonical JSON (RFC 8785) of a document and the `net_id` hash |
| `app/domain/net_validation.py` | domain | Validation shared by both formats (ids, arcs, references, P/T integers, bounds) and the JSON reader |
| `app/domain/pnml_import.py` | domain | Hardened PNML reader producing a `NetDocument`; errors located by line |
| `app/domain/pnml_export.py` | domain | Deterministic PNML rendered from a `NetDocument` (engine input and `Accept: application/pnml+xml`) |
| `app/domain/nets.py` | domain | `NetSummary`, `StoredNet`, `SavedNet`, `NetFormat`; summary of a document |
| `app/domain/pagination.py` | domain | `Paged` lists and opaque offset cursors |
| `app/domain/net_structure.py` | domain | `NetStructure`: places, transitions and arcs flattened from the page tree, references resolved |
| `app/domain/inspection.py` | domain | Inspection results (`NetOverview`, `ElementDetail`, `Neighbourhood`, `NameGroup`) and their computation |
| `app/domain/net_leak.py` | domain | Detect a net (PNML, XML, net document) in text bound for the LLM |
| `app/domain/base.py` | domain | `DomainModel`, the frozen base class of every model |
| `app/domain/formula.py` | domain | Formula tree (`Formula`, operators, atoms) and `subexpressions` |
| `app/domain/formula_text.py` | domain | Text syntax: parser, printer (reads back the same tree), logic inference |
| `app/domain/formula_check.py` | domain | Check a formula against a net: ids, operators of the logic, neXt, atom classes |
| `app/domain/engine_contract.py` | domain | The engine contract v1: `EngineRequest`, the entries of `result.json`, traces, `EngineReport` |
| `app/domain/engine_check.py` | domain | Check an engine report against the request and the net; ERROR for everything unusable |
| `app/domain/replay.py` | domain | Replay firings on a P/T net; evaluate a state condition on a marking |
| `app/domain/errors.py` | domain | Domain errors, the failures that are part of the API contract |
| `app/domain/contract.py` | domain | Shared JSON contract: `Envelope`, `ElementRef`, `Marking`, `Bound`, `Page` (docs/json-contract.md) |
| `app/application/ports.py` | application | Protocols the use cases need: `NetRepository`, `JobRepository`, `EngineGateway` |
| `app/application/nets.py` | application | `NetService`: convert an upload to the canonical document, store and read nets |
| `app/application/inspection.py` | application | `InspectionService`: summary, lists, element, search, marking, neighbourhood, name groups |
| `app/application/formulas.py` | application | `FormulaService`: parse and validate a formula against a net |
| `app/application/leases.py` | application | `LeaseKeeper`: renews a running job's lease so other processes know its owner is alive |
| `app/application/checks.py` | application | `CheckService`: submit, execute, read and cancel checks |
| `app/application/engines.py` | application | `EngineService`: list engines |
| `app/infrastructure/sqlite_store.py` | infrastructure | SQLite implementation of `NetRepository` and `JobRepository` |
| `app/infrastructure/docker_runner.py` | infrastructure | The only module that talks to Docker (SDK): isolated, labelled, always-removed engine containers (ADR 0016) |
| `app/infrastructure/engine_registry.py` | infrastructure | Engine specs and `EngineGateway` implementation |
| `app/api/deps.py` | api | FastAPI dependencies giving routes their services |
| `app/api/errors.py` | api | Domain error to RFC 9457 problem response, in one place |
| `app/api/nets.py` | api | Routes `/v1/nets`: upload JSON or PNML, download JSON or PNML |
| `app/api/negotiation.py` | api | `Content-Type` and `Accept` negotiation |
| `app/api/jobs.py` | api | Routes for checks and jobs |
| `app/api/engines.py` | api | Route `/v1/engines` |
| `app/api/inspection.py` | api | Read-only inspection routes under `/v1/nets/{id}` |
| `app/api/formulas.py` | api | Route `POST /v1/formulas/validate` |
| `app/api/envelopes.py` | api | Build the shared result envelope |
| `app/api/llm_tools.py` | api | Which routes may be offered to the LLM (all but the net itself) |
| `app/settings.py` | (config) | Pydantic settings from `PNVERIF_*` environment variables |
| `app/main.py` | main | Composition root: `create_app(settings=...)` |

## Dependency rules (enforced)

1. Layers: `main` > `api` | `infrastructure` > `application` > `domain`. Imports go downward only.
2. Domain and application import no web framework, no `sqlite3`, no `subprocess`, no Docker SDK.
3. Infrastructure imports no web framework.
4. Only `sqlite_store` imports `sqlite3`; only `docker_runner` imports the Docker SDK; nobody starts subprocesses.
5. `sqlite_store` and `docker_runner` are independent of each other and of the registry.

The contracts live in `api/pyproject.toml` (`[tool.importlinter]`). To see a rule fail on purpose,
add `from app.infrastructure import sqlite_store` to `app/application/nets.py` and run
`lint-imports`.

## Request flow: submitting a check

1. `POST /v1/nets/{net_id}/checks` reaches `app/api/jobs.py`, which validates the body into a
   `CheckRequest` and calls `CheckService.submit`.
2. `submit` loads the net, validates the engine name, builds a queued `Job` and asks the
   `JobRepository` to create it or return the equivalent live job (idempotency).
3. The route answers `202` with the job and, only if it is new, schedules `CheckService.execute`.
4. `execute` marks the job running (skipped if cancelled), loads the net, asks the `EngineGateway`
   to choose an engine and run it, turns an engine crash into `ERROR` verdicts, and stores results.
5. The client polls `GET /v1/jobs/{job_id}`.

## Data model

SQLite file, WAL mode. Table `nets` holds the summary and the canonical net document, compressed
(zlib); nets are immutable and identified by the hash of that document, whatever
format they were uploaded in. Table `jobs` holds state, request, results
and an idempotency key; a unique index guarantees one live job per key.

**Migration of a first-schema database** (nets stored as raw PNML under a file hash): opening the
database re-imports every stored net, stores its canonical document under the new id, repoints
the jobs (they get a fresh idempotency key), and swaps the table, all in one transaction. If a
stored net no longer imports, startup fails with the list of ids and the database is unchanged:
fix or delete those rows, then restart. General schema migrations are tracked in issue #5.

## How to extend

- **Add an engine**: add an image under `engines/<name>/` that follows `docs/engine-contract.md`,
  then one `EngineSpec` entry in `engine_registry.py`. No other code changes.
- **Add an endpoint**: a route in `app/api/`, a method in the matching service, a port method if the
  use case needs new storage or engine capabilities, then its adapter in `infrastructure/`.
- **Add a storage backend**: a new class implementing `NetRepository` and `JobRepository`, wired
  in `main.py`. Use cases do not change.

## Several processes

The API holds no state in memory that matters: any number of API processes (for example
`uvicorn --workers 4`, or several containers) can share the same database file on one host.
Coordination goes only through atomic conditional updates in the database:

- A job is **claimed** by `mark_running`; of several processes, exactly one wins.
- A queued or running job has a **lease** (`PNVERIF_JOB_LEASE_SECONDS`, default 60 s). The owner
  renews it three times per lease (`LeaseKeeper`) while the engine runs.
- Every process **sweeps** expired leases at submission and every half lease (lifespan task).
  A job whose owner died becomes `interrupted` and frees its idempotency key; a live job is never
  touched.
- **Cancellation** is a state change in the database; the owner sees it when its next renewal is
  refused, and `finish` never overwrites a cancelled or interrupted job.

SQLite needs a local filesystem shared by the processes (not NFS); several hosts need a server
database behind the same ports.

## Data contract
All data exchanged by the platform is structured JSON; the net is a canonical JSON document with
PNML as an alternative serialization chosen by content negotiation: see `docs/json-contract.md`,
`docs/net-document.md`, ADR 0013 and ADR 0015. The LLM never reads the net itself; it uses
inspection tools.
Each analysis and each transformation has its own endpoint and does one thing; the endpoint
names the operation, not the tool (ADR 0014). To add one: a route, a request model, a result
model, a use case run by the generic job runner, an entry in the operations catalog, and an engine
declaring it. The nets, inspection, formula, check, job, trace and replay routes follow that contract; analyses
and reductions (milestone M4) are not implemented yet.

## Known limitations

- Jobs run in the API process that received them (background tasks); cancelling a job stops its
  container at once, but a crashed API process leaves its job to the lease sweeper (issue #6).
- No schema migrations yet (see the storage issue).
- Mounting the Docker socket gives the API near-root access to the host: local use only. Risk
  analysis and the deployment plan: `docs/security-container-launching.md`.
