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
| `app/domain/descriptions.py` | domain | `Description`: immutable text identified by its hash, linked to a net with an origin |
| `app/domain/mcc.py` | domain | Model Checking Contest catalog: `MccFamily` parsed from the models page, `MccInstance` from archive members, `ModelEntry`, `SeedReport` |
| `app/domain/mcc_properties.py` | domain | The contest's formula XML read into formula trees (`parse_property_set`), `BoundQuery` for upper bounds; unknown elements are refused, never skipped |
| `app/domain/mcc_xml.py` | domain | Formula trees written as the contest's property XML (the inverse of `parse_property_set`), which verifypn and others read natively |
| `app/domain/capabilities.py` | domain | Classes of properties, the contest examinations a class needs, the capability table |
| `app/domain/equivalence.py` | domain | When engines are interchangeable for a class: known differences, caveats and breaks |
| `app/domain/portfolio.py` | domain | Merging the answers of several engines: shared verdicts, contradictions kept as evidence, settled only by a counterexample replayed on the net |
| `app/domain/patterns.py` | domain | Specification patterns (absence, response, bound, ...) instantiated into formulas deterministically |
| `app/domain/triviality.py` | domain | Properties the structure of the net already decides: vacuous premises, holds in every state, holds in none |
| `app/domain/conformance.py` | domain | Conformance cases, the engine-by-case matrix, wrong answers and contradictions flagged for triage |
| `app/domain/operations.py` | domain | The operations (analyses, reductions): `OperationDefinition`, the request, the run and its outcome |
| `app/domain/operation_check.py` | domain | Checks what an engine says an operation found: the shape, and only elements the net has, with their names |
| `app/domain/catalog.py` | domain | Every operation (analyses and reductions) and `find_operation` |
| `app/domain/perform.py` | domain | Perform a named operation on a document: its result, and for a reduction the net it produced |
| `app/domain/lifting.py` | domain | A counterexample of a reduced net expressed on the original, through the expansions of each reduction |
| `app/domain/analysis_summary.py` | domain | The size-bounded digest of the analyses given to the LLM: exact counts, a few named examples, and what could not be computed |
| `app/domain/colored.py` | domain | Colored nets, typed: sorts, variables and their sizes, read from the declarations; unsupported constructs refused by name |
| `app/domain/colored_terms.py` | domain | Arc inscriptions, markings and guards of colored nets as typed trees |
| `app/domain/colored_summary.py` | domain | The colored net at a glance: sorts, groups of places and transitions, color functions, size of the unfolding |
| the package `app/domain/analyses` | domain | The analyses, one module each; its `__init__` is the catalog `ANALYSES` and `find_operation` |
| `app/domain/reductions/result.py` | domain | The request and answer of every reduction rule: protected ids, removed, merged, expansions, preserved properties |
| `app/domain/reductions/driver.py` | domain | The loop every rule shares: apply until it no longer applies, and report what changed |
| `app/domain/reductions/working.py` | domain | The private mutable copy of a net that rules rewrite |
| `app/domain/reductions/document.py` | domain | A reduced structure written back as a net document |
| `app/domain/reductions/removals.py` | domain | Rules `remove-dead-transitions` and `remove-self-loop-transitions` |
| `app/domain/reductions/parallel.py` | domain | Rules `fuse-parallel-places` and `fuse-parallel-transitions` |
| `app/domain/reductions/series.py` | domain | Rules `fuse-series-places` and `fuse-series-transitions` (Berthelot), with expansions for lifting |
| `app/domain/reductions/implicit.py` | domain | Rule `remove-implicit-places`: sink places and places dominated by another |
| `app/domain/reductions/agglomeration.py` | domain | Rules `pre-agglomeration` and `post-agglomeration` (Berthelot): fuse the transitions around an empty buffer place |
| the package `app/domain/reductions` | domain | The reduction rules; its `__init__` is the list `REDUCTIONS` |
| `app/domain/analyses/t_invariants.py` | domain | Analysis `t-invariants`: semiflows of the transposed incidence matrix |
| `app/domain/analyses/place_bounds.py` | domain | Analysis `place-bounds`: bounds from the P-invariants; unbounded only when a source transition feeds a place |
| `app/domain/analyses/siphons.py` | domain | Analyses `minimal-siphons` and `minimal-traps`: branching search over the violated transitions |
| `app/domain/analyses/dead_transitions.py` | domain | Analysis `dead-transitions`: least fixpoint of markable places and firable transitions |
| `app/domain/analyses/conflict_sets.py` | domain | Analysis `conflict-sets`: transitions linked by shared input places |
| `app/domain/analyses/connected_components.py` | domain | Analysis `connected-components`: weak connectivity of the net |
| `app/domain/analyses/incidence.py` | domain | The incidence matrix of a P/T net |
| `app/domain/analyses/invariants.py` | domain | Options and weighted elements shared by the invariant analyses |
| `app/domain/analyses/net_class.py` | domain | Analysis `net-class`: state machine, marked graph, free choice, workflow-like |
| `app/domain/analyses/p_invariants.py` | domain | Analysis `p-invariants`: minimal-support place invariants with their constants |
| `app/domain/analyses/semiflows.py` | domain | Minimal-support semiflows of an integer matrix (Farkas), shared by P- and T-invariants |
| `app/domain/analyses/graph.py` | domain | Arc adjacency and reachability shared by the analyses |
| `app/domain/next_moves.py` | domain | What to try after a timeout, out-of-memory, UNKNOWN or error: suggestions that never become a verdict |
| `app/domain/baseline.py` | domain | Baseline B0: standard properties written from the structure of a net, no language model (`bench/README.md`) |
| `app/domain/soundness.py` | domain | Audit of a session log against the jobs it cites: findings for unsupported verdicts, contradictions listed (measure M1) |
| `app/domain/non_triviality.py` | domain | Measure M4: share of properties neither vacuous nor decided by the structure, per family then per condition |
| `app/domain/mutation.py` | domain | Mutants of a P/T net: arc removed or added, weight or initial marking changed, transition removed; chosen from a seed |
| `app/domain/mutation_score.py` | domain | Judging mutants against a property set: killed, survived or undecided; mutation score (M5), seeded fault finding (M6) |
| `app/domain/obfuscation.py` | domain | Condition N: deterministic renaming of a P/T net's elements (all names dropped) and the way back for properties |
| `app/domain/experiment.py` | domain | An experimental run: condition, budget, provenance (seed, commit, tools, model, prompt) and the record of what was measured |
| `app/domain/conditions.py` | domain | What each condition (L1, L2, L3, N) gives the model: tools, description, the goal, the hash of the prompt |
| `app/domain/predictor.py` | domain | Instance features, decision trees (CART) giving the chance an engine answers, the `Predictor` model |
| `app/domain/selection_evaluation.py` | domain | Training the predictor from contest runs and scoring it against the single best engine and the oracle, by family |
| `app/domain/mcc_results.py` | domain | The contest's published runs: tool names normalized, the contest's own outcome classes kept (never a verdict), success rate and median time per family |
| `app/domain/splits.py` | domain | Frozen, seeded split of families into balanced development folds and a held-out test set (the family is the unit) |
| `app/domain/sessions.py` | domain | `Session`, the frozen event vocabulary (`SessionEvent`) and `StoredEvent`; a verdict cannot be built without an engine result |
| `app/domain/llm.py` | domain | What the LLM port exchanges: `LlmMessage`, `LlmToolCall`, `ToolSpec`, `LlmStep` |
| `app/domain/tool_inputs.py` | domain | The arguments of each tool offered to the LLM (their JSON Schemas are what the model sees) |
| `app/domain/conversation.py` | domain | The system prompt, the quoting of untrusted text and the messages the LLM sees, built from the events |
| `app/domain/report.py` | domain | The report of a session (structured and Markdown), built from the events; verdicts only from engine results |
| `app/domain/errors.py` | domain | Domain errors, the failures that are part of the API contract |
| `app/domain/contract.py` | domain | Shared JSON contract: `Envelope`, `ElementRef`, `Marking`, `Bound`, `Page` (docs/json-contract.md) |
| `app/application/ports.py` | application | Protocols the use cases need: `NetRepository`, `JobRepository`, `EngineGateway` |
| `app/application/nets.py` | application | `NetService`: convert an upload to the canonical document, store and read nets |
| `app/application/inspection.py` | application | `InspectionService`: summary, lists, element, search, marking, neighbourhood, name groups |
| `app/application/formulas.py` | application | `FormulaService`: parse and validate a formula against a net |
| `app/application/workers.py` | application | `WorkerPool`: threads that claim and run queued jobs |
| `app/application/descriptions.py` | application | `DescriptionService`: add and read net descriptions |
| `app/application/tools.py` | application | `ToolFacade`: the tools of the agent over the use cases; trimmed JSON answers (ADR 0017), events for checks and questions |
| `app/application/agent.py` | application | `AgentService`: sessions, user messages and answers, and the agent run (budgets, resumable, cancellable) |
| `app/application/log_context.py` | application | The request id of the request being served, read by the log formatter |
| `app/application/retention.py` | application | `RetentionService`: delete sessions, nets and descriptions, and apply the retention policy |
| `app/application/models.py` | application | `ModelCatalogService`: seed the platform with contest nets (family, instance, `mcc` description) and list them |
| `app/application/conformance.py` | application | `ConformanceService`: the same cases through the engine gateway for several engines |
| `app/application/operations.py` | application | `OperationService`: describe, submit, run and read operations; a finished run is the cache of its key |
| `app/application/tool_kit.py` | application | What every tool is made of: context, outcome, trimmed JSON answers |
| `app/application/analysis_runner.py` | application | Submit an analysis from inside a tool and wait for it, working the queue meanwhile |
| `app/application/advice_tools.py` | application | The tools `select_tools` and `classify_counterexample`, and the moves proposed after a non-answer (other engine, longer timeout, simpler or weaker property) |
| `app/application/analysis_tools.py` | application | The tools `analysis_summary` and `analyze`: the operation runner as the agent's tools |
| `app/application/traces.py` | application | `TraceService`: counterexamples on the original net or the reduced one they were found on |
| `app/application/results.py` | application | `ResultsService`: import the published results (all or nothing) and summarize them |
| `app/application/splits.py` | application | `SplitService`: freeze a split of the catalog's families and read it back |
| `app/application/leases.py` | application | `LeaseKeeper`: renews a running job's lease so other processes know its owner is alive |
| `app/application/checks.py` | application | `CheckService`: submit, execute, read and cancel checks |
| `app/application/selection.py` | application | `SelectionService`: capable engines for some formulas on a net, ranked by a trained model, contest history or a fixed order |
| `app/application/predictor_training.py` | application | `PredictorTrainer`: train the engine predictor on the development families of a split, pick its margin by cross-validation |
| `app/application/soundness.py` | application | `SoundnessAuditor`: read sessions and the jobs their verdicts cite, and report what does not hold |
| `app/application/experiment.py` | application | `ExperimentRunner`: the deterministic judge, measuring a property set on a net and its mutants under a budget |
| `app/application/experiment_sessions.py` | application | `ModelConditionRunner`: a session of the model in non-interactive mode, then the common measurement |
| `app/application/engines.py` | application | `EngineService`: list engines (with filters), capabilities, equivalence |
| `app/infrastructure/sqlite_store.py` | infrastructure | SQLite implementation of `NetRepository` and `JobRepository` |
| `app/infrastructure/sqlite_database.py` | infrastructure | The shared base of the SQLite adapters: the file, its migration, short-lived connections |
| `app/infrastructure/sqlite_retention.py` | infrastructure | Deletion of user data along its references |
| `app/infrastructure/sqlite_catalog.py` | infrastructure | Contest families and the nets that are their instances |
| `app/infrastructure/sqlite_results.py` | infrastructure | Published runs and the provenance of each result set |
| `app/infrastructure/sqlite_splits.py` | infrastructure | Frozen splits; a name can be stored once |
| `app/infrastructure/sqlite_operations.py` | infrastructure | Runs of operations: an atomically claimed queue, leases, and the result cache |
| `app/infrastructure/mcc_source.py` | infrastructure | Contest files on disk: resumable download, SHA-256 recorded on first download and checked afterwards, reading of family archives |
| `app/infrastructure/sqlite_migrations.py` | infrastructure | Numbered schema migrations (`PRAGMA user_version`), including the conversion of first-schema databases |
| `app/infrastructure/sqlite_backup.py` | infrastructure | Online backup and offline restore of the database |
| `app/infrastructure/scripted_llm.py` | infrastructure | `ScriptedLlm`, the double of the LLM port, and `DemoLlm`, an offline demonstration |
| `app/infrastructure/anthropic_llm.py` | infrastructure | The Anthropic Messages API behind the LLM port; the only module that imports the provider SDK |
| `app/infrastructure/unavailable_llm.py` | infrastructure | The LLM gateway when none is configured: refuses with the setting to change |
| `app/infrastructure/json_logging.py` | infrastructure | Structured logs: one JSON object per line |
| `app/infrastructure/docker_runner.py` | infrastructure | The only module that talks to Docker (SDK): isolated, labelled, always-removed engine containers (ADR 0016) |
| `app/infrastructure/engine_registry.py` | infrastructure | Engine specs and `EngineGateway` implementation |
| `app/api/deps.py` | api | FastAPI dependencies giving routes their services |
| `app/api/errors.py` | api | Domain error to RFC 9457 problem response, in one place |
| `app/api/nets.py` | api | Routes `/v1/nets`: upload JSON or PNML, download JSON or PNML |
| `app/api/negotiation.py` | api | `Content-Type` and `Accept` negotiation |
| `app/api/jobs.py` | api | Routes for checks and jobs |
| `app/api/engines.py` | api | Route `/v1/engines` |
| `app/api/models.py` | api | Routes `/v1/models` and `/v1/models/families` |
| `app/api/operations.py` | api | `GET /v1/operations`, one `POST` route per operation built from its definition, `GET`/`DELETE /v1/runs/{id}` |
| `app/api/inspection.py` | api | Read-only inspection routes under `/v1/nets/{id}` |
| `app/api/formulas.py` | api | Route `POST /v1/formulas/validate` |
| `app/api/descriptions.py` | api | Routes for net descriptions |
| `app/api/sessions.py` | api | Sessions: start, messages, answers, cancel, events (JSON or server-sent events) |
| `app/api/middleware.py` | api | Request id and access log |
| `app/api/envelopes.py` | api | Build the shared result envelope |
| `app/api/llm_tools.py` | api | Which routes may be offered to the LLM (all but the net itself) |
| `app/settings.py` | (config) | Pydantic settings from `PNVERIF_*` environment variables |
| `app/main.py` | main | Composition root: `create_app(settings=...)` |
| `app/train_predictor.py` | main | `python -m app.train_predictor --split NAME --out FILE`: train and validate the engine predictor, write it as JSON |
| `app/audit_sessions.py` | main | `python -m app.audit_sessions [--session ID]`: prints the soundness report, exits 1 when a verdict is unsupported |
| `app/run_experiment.py` | main | `python -m app.run_experiment --split NAME`: run a condition on the families of a split, one JSON record per run |
| `app/seed.py` | main | `python -m app.seed [family...]`: download and store contest models; nothing downloaded is versioned |
| `app/conformance.py` | main | `python -m app.conformance --cases FILE`: loads cases, runs them, prints the matrix, exits 1 when a row needs triage |

## The chat workflow
A session is a conversation about one net (ADR 0008). Its log is the `events` table; the state is
`queued`, `running`, `waiting_for_user`, `idle` or `cancelled`. A user message or an answer queues a
run; a worker (the same pool that runs checks) claims it atomically and keeps a lease. The run
rebuilds what the model sees from the events (`domain/conversation.py`), asks the LLM port for the
next step, runs the tools of the facade (`application/tools.py`) and records everything as events.
It ends when the model stops calling tools, asks the user a question, or reaches a budget
(`PNVERIF_AGENT_*`). A worker that dies leaves the run to the sweeper, which queues it again: it
resumes from its events. The only verdict events come from tools that took them from engine results.
Clients read `GET /v1/sessions/{id}/events` as JSON or as server-sent events (resumable with
`Last-Event-ID`), from the database, so any process can serve any session.

The language model is `PNVERIF_LLM_PROVIDER`: `none` (sessions end with an explanatory error),
`scripted` (an offline demonstration with no key) or `anthropic` (key in `PNVERIF_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY`, model in `PNVERIF_ANTHROPIC_MODEL`, default `claude-opus-4-8`). The adapter switches thinking off so the history rebuilt from the events stays valid; a model that binds its thinking blocks to the conversation needs the provider's reasoning state kept with the events (backlog).

## The UI
`ui/` is a TypeScript (strict), React and Vite project (ADR 0010), a thin client of the REST API:
it offers nothing the API does not. Its types are generated from `docs/openapi.json`
(`make openapi`, then `npm run gen:api` in `ui/`), which comes from the pydantic models; a hook and
the CI fail when either is stale, so an API change that breaks the UI fails the build. Biome
(lint and format), `tsc --strict`, Vitest and Testing Library run in the `ui` hook and CI job
(`make ui-check`, Node 22, see `ui/.nvmrc`). The built files (`ui/dist`) are served under `/ui`
by the API when `PNVERIF_UI_DIR` points to them; the API image builds them in a first stage.
Event data is rendered as React text, never as HTML.

The chat has two screens, chosen by the address (`#/session/<id>` keeps its place): the **start
form** (upload the net, which shows what the platform understood; an optional description typed or
from a `.txt`/`.md` file; the goal) and the **conversation** (`SessionView`). The conversation
follows `GET /v1/sessions/{id}/events` with a `fetch`-based client that reconnects by itself and
resumes after the last event (`Last-Event-ID`); the state of the session is derived from the events
alone, so the page needs no polling. Verdicts are shown with their words, their engine and its
version, never by colour alone; the assistant's text is labelled as written by the language model;
a question opens an answer box; the user can cancel.

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
3. The route answers `202` with the job (new, or the equivalent live one). The job waits in the
   queue.
4. A worker (`WorkerPool`, in any process) claims the oldest queued job atomically, loads the net,
   asks the `EngineGateway` to choose an engine and run it, checks the report, turns an engine
   crash into `ERROR` verdicts, and stores results and counterexamples.
5. The client polls `GET /v1/jobs/{job_id}`.

## Data model

SQLite file, WAL mode. Table `nets` holds the summary and the canonical net document, compressed
(zlib); nets are immutable and identified by the hash of that document, whatever
format they were uploaded in. Tables `sessions` and `events` hold conversations (ADR 0008): events are numbered 1, 2, 3... per
session by the INSERT itself, so concurrent writers never share or skip a number. Table `jobs` holds state, request, results
and an idempotency key; a unique index guarantees one live job per key.

**Schema versions.** The version is `PRAGMA user_version`; migrations are numbered, applied in
order at start-up in one `BEGIN IMMEDIATE` transaction (so several processes starting together
migrate once), and never edited after release. A database from a newer software version is
refused, not damaged. A change of schema is a new migration in `sqlite_migrations.py`.

**Retention.** `PNVERIF_JOB_RETENTION_DAYS` (unset: keep everything) makes the lease sweeper delete
finished jobs, with their counterexamples, not touched for that long. Queued and running jobs are
kept; nets are never deleted (they are immutable and may be used again).

**Backups.** `python3 scripts/db_backup.py backup data/pnverif.sqlite backups/<date>.sqlite` uses
SQLite's online backup API: consistent while the API runs. To restore, stop every API process, then
`python3 scripts/db_backup.py restore backups/<date>.sqlite data/pnverif.sqlite` (it checks the
backup, removes the old write-ahead files and copies it). If the database grows too large, net
documents can move to content-addressed files without changing the ports.

**Migration of a first-schema database** (nets stored as raw PNML under a file hash): opening the
database re-imports every stored net, stores its canonical document under the new id, repoints
the jobs (they get a fresh idempotency key), and swaps the table, all in one transaction. If a
stored net no longer imports, startup fails with the list of ids and the database is unchanged:
fix or delete those rows, then restart. General schema migrations are tracked in issue #5.

## How to extend

- **Add an engine**: copy `engines/template/` to `engines/<name>/` (the adapter kit
  `engines/common/pnverif_engine` does the plumbing), then add one `EngineSpec` entry in
  `engine_registry.py`. No other code changes. Checklist: `docs/engine-integration-checklist.md`.
- **Add an endpoint**: a route in `app/api/`, a method in the matching service, a port method if the
  use case needs new storage or engine capabilities, then its adapter in `infrastructure/`.
- **Add a storage backend**: a new class implementing `NetRepository` and `JobRepository`, wired
  in `main.py`. Use cases do not change.

## Several processes

The API holds no state in memory that matters: any number of API processes (for example
`uvicorn --workers 4`, or several containers) can share the same database file on one host.
Coordination goes only through atomic conditional updates in the database:

- A job is **claimed** by `claim_next_job`, one conditional `UPDATE ... RETURNING`; of several
  workers in several processes, exactly one wins. The queue is the `jobs` table (ADR 0018).
- A running job has a **lease** (`PNVERIF_JOB_LEASE_SECONDS`, default 60 s). The owner
  renews it three times per lease (`LeaseKeeper`) while the engine runs.
- Every process **sweeps** expired leases at submission and every half lease (lifespan task).
  A running job whose owner died becomes `interrupted` and frees its idempotency key; a live or
  waiting job is never touched. `POST /v1/jobs/{id}/retry` queues an interrupted job again.
- Workers: each API process runs `PNVERIF_EMBEDDED_WORKERS` threads; `python -m app.main` runs
  workers only (`PNVERIF_WORKER_THREADS`).
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

## Retention and deletion
User data (nets, descriptions, sessions) can be confidential. Nets and descriptions are shared by
content (the same upload is one record), so deletion follows references: `DELETE /v1/sessions/{id}`
cancels the run and deletes the session with its events; `DELETE /v1/nets/{id}` deletes a net that
nothing uses, or with `?cascade=true` also its jobs, counterexamples, sessions and description
links (409 while something is queued or running); `DELETE /v1/descriptions/{id}?net_id=` unlinks a
description, and its text goes when no net links to it. Automatic policy, off by default:
`PNVERIF_SESSION_RETENTION_DAYS` (sessions not touched for that long, unless running),
`PNVERIF_UNREFERENCED_NET_RETENTION_DAYS` (nets no job or session uses, and unlinked descriptions),
`PNVERIF_JOB_RETENTION_DAYS` (finished jobs), `PNVERIF_SESSION_WAITING_EXPIRY_DAYS` (sessions
waiting for an answer). **There is no authentication yet**: any client can delete; a shared
deployment must put the API behind authentication first.

## Logs
Logs go to standard error as one JSON object per line (`PNVERIF_LOG_LEVEL`, `PNVERIF_LOG_JSON`).
Every request gets an id (the client's `X-Request-ID` if it looks like one, else a new one),
returned in the response and present in every line logged while serving it. Jobs log `job_started`
and `job_finished` with the job id, net id, engine, duration and verdicts; agent runs log
`run_started` and `run_finished` with the session id. Logs carry identifiers and measures, never
PNML, net documents, descriptions or messages.

## Budgets
Beyond ruff's complexity limits, `scripts/check_budgets.py` (a hook and a CI step) keeps code
readable: at most 700 lines per module, 130 lines per function and 40 methods per class. A module
that outgrows its budget is split along a real concept, not along line numbers.

## Known limitations

- Workers poll the database (`PNVERIF_WORKER_POLL_SECONDS`); one host only (ADR 0018).
- Mounting the Docker socket gives the API near-root access to the host: local use only. Risk
  analysis and the deployment plan: `docs/security-container-launching.md`.
