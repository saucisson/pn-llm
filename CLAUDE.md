# pn-llm-verif

Prototype: an LLM proposes properties to check on a Petri net, relying on static-analysis and
model-checking tools exposed through a REST API. Nets come from the MCC collection (P/T and
colored) or from users.

**Guiding principle: the LLM generates hypotheses, the tools arbitrate.** The LLM never "proves"
anything; every verdict comes from an engine, with its name, version and limits.

**Goal of the code base: stay readable and easy to evolve.** The rules below exist for that.

## Language

Everything is written in **English**: code, identifiers, comments, docstrings, docs, commit
messages, issues, pull requests. (Conversation with the maintainers may be in French.)

## Code rules (follow them for every change)

Full text, examples and enforcement: `docs/conventions.md`. Summary:

1. **Linear functions.** Do not split a function into helpers just to shorten it. Extract only for
   reuse or for a real concept with its own tests. One-use `_private` helpers are a smell: inline.
2. **Pydantic for all data.** Every structure is a pydantic model, never a dict, tuple or dataclass:
   bodies, entities, settings, return values, grouped parameters, file contents. Domain models
   derive from `DomainModel` (**frozen**); use `tuple[...]`, not `list[...]`, in models. Return a
   model instead of an anonymous tuple. Read/write JSON through pydantic.
3. **Named parameters, always.** Every parameter is keyword-only (`def f(*, a, b)`), every call
   names its arguments. Exceptions: `self`, exception messages, imposed framework callbacks
   (`# noqa: PLR0917` with a reason), test functions.
4. **Never mutate a parameter.** Return new values; do not modify arguments or shared state you
   were handed; do not reassign parameter names. State changes happen only in adapters.
5. **Onion architecture.** `main > (api | infrastructure) > application > domain`. Dependencies
   point inward only. `api` never imports `infrastructure` and vice versa; use cases depend on
   **ports** (`application/ports.py`), not on adapters. Only `main.py` wires layers together.
6. **Comments and docstrings.** Docstring (imperative one-liner) on every public module, class,
   function, method. Comments say *why*, not *what*. No commented-out code. No TODO/FIXME: open an
   issue. Every `noqa` / `type: ignore` carries a reason.
7. **Types and errors.** Fully typed (`mypy --strict`). No `assert` in production code. Expected
   failures are domain errors mapped to HTTP in one place (`api/errors.py`).

## Architecture

Layers, modules, dependency rules, request flow, how to extend, known limitations:
`docs/architecture.md`. Decisions and their reasons: `docs/adr/`. **Keep `docs/architecture.md`
in sync with the code in the same commit** (a hook checks that every module is documented). Add
an ADR for any significant decision.

## Quality gates (run automatically; run them yourself before declaring a task done)

```bash
make setup      # once: virtualenv, dependencies, git hooks
make check      # everything below, as in CI
make format     # ruff format + autofix
make lint       # ruff check
make typecheck  # mypy --strict
make arch       # import-linter: the onion rules
make docs-check # architecture doc in sync with the modules
make cov        # tests with branch coverage (minimum 95 %); Docker tests: make docker-test
```

| When | What runs |
|---|---|
| every commit | file hygiene, ruff (lint + format), mypy, import-linter, docs sync, shellcheck, conventional commit message |
| every push | full tests with coverage threshold |
| every PR (CI) | all of the above, `pip-audit`, Docker image builds |

Do not bypass hooks (`--no-verify`). If a rule seems wrong, change the rule in a reviewed commit
(and the ADR/convention doc), do not work around it. Tests policy: `docs/testing.md` (a behaviour
change always comes with a test; no mocks of our own code; coverage floor 95 %).

## Workflow for a change

1. Read `docs/conventions.md` and `docs/architecture.md` if you have not this session.
2. Write the test first for a bug fix; add tests with every behaviour change.
3. Put code in the right ring (see architecture); add a port method if a use case needs a new
   capability, and its adapter.
4. Run `make check`. Update docs (and an ADR if it is a decision) in the same commit.
5. Conventional commit message (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`), one
   concern per commit.
6. Pull request: put `Closes #N` (one per line, one keyword per issue) in the **description** of
   the PR for every issue it fully resolves, so that GitHub closes them at merge. "Implements #N"
   or "(#N)" in a title closes nothing. If an acceptance criterion is not met, write `Refs #N`
   instead and say what remains in a comment on the issue. After the merge, check that the issues
   are closed. Merge with a rebase (the only method the repository allows) only when CI is green.

## Domain rules that must never be broken

1. **UNKNOWN is not FALSE.** Timeout, out-of-memory, error and "don't know" are never converted
   into a verdict. Valid verdicts: TRUE, FALSE, UNKNOWN, TIMEOUT, OOM, ERROR (ADR 0006).
2. **An engine adapter never changes the semantics of a formula.** Any adapter change must pass
   known-verdict tests (at least one TRUE and one FALSE per engine and supported syntax).
3. **Reductions never remove or merge a place or transition cited in a formula**
   (`observed_places`). No stutter-sensitive reduction for an LTL formula using neXt.
4. **Counterexamples are reported on the original net** (through the mapping), not the reduced one.
5. **Engines run in ephemeral containers**: no network, read-only filesystem, memory/CPU/pids
   limits, timeout with kill. Never run an engine on the host (ADR 0004).
6. **Pinned versions** (tag or commit) in every engine Dockerfile; the version is recorded in
   every result.
7. Place and transition **names and ids from the net are kept as-is** (no normalization, not even
   Unicode): they are the semantic signal the LLM needs.
8. **Contradictory verdicts between equivalent tools are reported, never silently resolved.**
9. The API must stay **multi-process safe**: no state in memory that matters, jobs claimed by
   atomic conditional updates, liveness by renewable leases, no start-up-order or "only one
   instance" assumption (ADR 0003, `docs/architecture.md`). Never write "run a single process".
10. **Structured JSON everywhere.** The net has a canonical JSON document (pages, graphics,
    tool-specific data, P/T and colored, `docs/net-document.md`, ADR 0015); PNML is an alternative
    serialization chosen with `Accept` and `Content-Type` (JSON is the default). Analyses, reductions, formulas,
    checks, traces and sessions are pydantic models serialized as JSON, with the shared envelope,
    `ElementRef`, pagination and formula tree of `docs/json-contract.md` (ADR 0013). Reuse the
    shared model for a concept; do not invent a new shape. **One endpoint per analysis or
    transformation, doing one thing** (one analysis type, one reduction rule), named after the
    operation and not the tool (ADR 0014).
11. **The LLM never reads the net itself**: not PNML, not XML, not the JSON net document. It
    learns about a net through inspection tools (places, transitions, neighbourhoods, name groups,
    ...). `GET /v1/nets/{id}` is excluded from its tools. A guard test enforces it.
12. Nets are **immutable** and identified by the hash of their **canonical JSON document**, not of
    the uploaded file (ADR 0015); a transformation creates a new net linked to its parent
    (ADR 0005). Conversion between PNML and JSON must lose no semantic information.

## Persistence and configuration

SQLite (WAL), behind the repository ports (ADR 0003). Persistent: nets and jobs survive restarts;
an equivalent request returns the same job, also across restarts. Settings are a pydantic
`Settings` read from `PNVERIF_*` variables (`PNVERIF_DATABASE_PATH`, default
`data/pnverif.sqlite`, git-ignored; a Docker volume in docker-compose). Schema changes need a
migration once real data exists (backlog).

## Environment: WSL2 / Ubuntu

- Work under `~/...` (Linux filesystem), **never** under `/mnt/c/...` (very slow).
- WSL2 memory: set `memory=` in `%UserProfile%\.wslconfig`; keep container `mem_limit` below it.
- Docker: Docker Desktop (WSL integration) or native Docker Engine with `systemd=true` in
  `/etc/wsl.conf` and the user in the `docker` group.
- Mounting `/var/run/docker.sock` in the API container is acceptable locally, not deployed.
- Hooks and `make` use the tools of the active virtualenv (`make setup` creates `api/.venv`).
- Timing under WSL2 is noisy: run final benchmarks on native Linux.

## Evaluation (respect this when touching bench/)

Goal and claims: `docs/objective.md`. Protocol, conditions, measures, thresholds:
`docs/evaluation.md` (ADR 0012). Rules that must not be broken:

- The judge is deterministic (engines, replay, mutation); no LLM grades LLM output.
- Always compare against the rule-based baseline B0 with the **same budget**, and run the
  ablations (net only, + static analysis, + description, names obfuscated).
- Unit of analysis and splits are **model families**, never instances. Tune on dev families only;
  the test set is run once per frozen version (`eval-freeze-N` tag).
- MCC models are public (possible contamination): also use unpublished models; report separately.
- Mutants that cannot be decided are reported as undecided, never as killed or equivalent.
- Record model id, prompt hash, tool versions, seeds and budgets; log negative results.
- Soundness (zero unsupported verdicts) is a defect check, not a result to optimize.

Publication targets (Petri Nets conference, paper types and what each needs): `docs/publication.md`.

## Backlog and scope

The backlog is created by `scripts/create_issues.sh` (milestones M1 to M9). **Next workflow: a
text-only chat (M8; proposed ADRs 0008-0010, to be reviewed before any code).** The user hands over
a net and a goal; the LLM works, shows its steps, reports intermediate results and may ask
questions. **No graphical display of nets for now** (M9 is deferred): quote place and transition
names as text. **Exploration (M7,
`docs/exploration.md`) is deferred**: do not start it unless asked. The LLM may only be used in
unconventional ways where a deterministic judge stands between it and the user.

## Repository map

```
api/            the application (app/) and its tests (tests/); pyproject.toml holds all tool config
ui/             the text chat UI (TypeScript strict, React, Vite, Biome, Vitest); types generated from docs/openapi.json
engines/<name>/ one Docker image per engine, common contract (docs/engine-contract.md); engines/common = adapter kit, engines/template = image template
bench/          evaluation scripts and MCC import (models themselves are not versioned)
scripts/        create_issues.sh (backlog), check_architecture_doc.py (docs sync hook)
docs/           objective, roadmap (order of the backlog), evaluation protocol, publication targets, JSON contract, net document, architecture, conventions, testing, ADRs, engine contract, MCC tools, exploration
```
