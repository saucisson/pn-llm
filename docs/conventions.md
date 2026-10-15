# Code conventions

These rules apply to every line of code in this repository, whoever writes it (humans and Claude
Code alike). Each rule says **why**, **how to apply it** and **what enforces it**. A rule enforced
only by review is marked *review*.

Goal: a code base that stays readable and easy to evolve.

## 1. Linear functions: no artificial splitting

Write a function so that it reads top to bottom. Do not cut it into helpers just to make it
shorter or to satisfy a metric. A reader should not have to jump around to follow one thought.

- Extract a function only when it is **reused**, or when it is a **real concept** with its own
  name and its own tests (for instance `EngineRegistry.choose`, a policy that will change).
- Do not extract a block merely because it is long, or to give a name to two lines.
- Nested helper functions and one-use `_private` functions are a smell: inline them.
- Comments inside a long function mark its steps; they explain *why*, not *what*.

Bad: `summarize()` calling `_name()`, `_initial_tokens()`, `_text_of()`, `_local()`, each used once.
Good: one `summarize()` that walks the document once (see `app/domain/pnml.py`).

Enforcement: ruff complexity limits are deliberately generous (McCabe 15, 15 branches, 60
statements) so that they only catch real tangles, not linear code. Otherwise *review*.

## 2. Pydantic for all data

Every structured piece of data is a pydantic model, not a dict, tuple, dataclass or `NamedTuple`:
API bodies, domain entities, settings, results returned by functions, parameters grouped together,
engine output files.

- Domain models derive from `DomainModel` (`app/domain/models.py`): **frozen**, so a value never
  changes after creation.
- Collections inside models are tuples (`tuple[str, ...]`), not lists, so that frozen means frozen.
- A function that returns two related values returns a model (`JobSubmission`, `StoredNet`), never
  an anonymous tuple.
- Settings come from `pydantic-settings` (`app/settings.py`), prefixed `PNVERIF_`.
- JSON is read and written through pydantic (`model_validate_json`, `TypeAdapter`), never by hand.

Enforcement: `tests/unit/test_models.py` fails if a domain model is not frozen; mypy strict with the
pydantic plugin. Using a plain dict or dataclass for domain data is caught in *review*.

## 3. Named parameters, always

Every parameter of every function and method is **keyword-only** (after a bare `*`), and every
call names its arguments.

```python
def register(self, *, payload: bytes) -> NetSummary: ...


nets.register(payload=body)
```

Exceptions: `self`/`cls`, the message of an exception (`NotFoundError("...")`), framework callbacks
whose signature is imposed (mark with `# noqa: PLR0917` and say why), and test functions (pytest
injects fixtures by name).

Enforcement: ruff `PLR0917` with `max-positional-args = 0`. A positional call to a keyword-only
function fails at run time and in mypy.

## 4. Never mutate a parameter

A function never changes its arguments and never mutates shared state it was handed.
It returns new values. Local variables are fine; building a list locally and returning it is fine.

- Domain models are frozen, which makes mutating them an error.
- Do not append to a list or update a dict that came from the caller.
- Do not reassign a parameter name inside the function (use a new name).
- State changes happen in one place only: the adapters behind the ports (for instance a SQL
  `UPDATE` in `SqliteStore`).

Enforcement: frozen models; ruff `PLW2901` and `B` rules catch some cases. The rest is *review*.

## 5. Onion architecture

Dependencies point inward only. Details and rationale: `docs/architecture.md`.

```
main  >  ( api | infrastructure )  >  application  >  domain
```

- `domain`: models, errors, net document and PNML conversion. Imports nothing from the other layers.
- `application`: use cases and the **ports** (protocols) they need. Imports the domain only.
- `infrastructure`: adapters implementing the ports (SQLite, Docker, engine registry).
- `api`: HTTP routes. Calls the application layer only; never an adapter.
- `main`: composition root; the only module that knows every layer.

Enforcement: import-linter contracts in `api/pyproject.toml`, run at every commit and in CI.

## 6. Comments and docstrings

- Every public module, class, function and method has a docstring: one imperative summary line
  ("Return ...", "Raise ..."). Add `Raises:` when the function raises on purpose.
- Comments explain **why** (a constraint, a trade-off, a surprise), never **what** the code does.
- No commented-out code: delete it, git remembers.
- No `TODO`, `FIXME`, `XXX`, `HACK`: open a GitHub issue instead. Work to do lives in the backlog.
- A `noqa` or `type: ignore` always carries a reason on the same line.
- Language: English, in code, comments, docs, commit messages and issues.

Enforcement: ruff `D` (docstrings), `ERA` (commented-out code), `FIX` (TODO markers), `RUF100`
(unused `noqa`). The quality of a comment (why, not what) is *review*.

## 7. Types

Production code is fully typed and passes `mypy --strict`. No `Any` without a reason. No `assert`
for control flow or type narrowing in production code (asserts disappear under `python -O`); raise
a domain error or restructure.

Enforcement: mypy strict; ruff `S101` (assert) outside tests.

## 8. Errors

Expected failures are domain errors (`app/domain/errors.py`), mapped to HTTP statuses in one place
(`app/api/errors.py`). Never return `None` or a magic value to signal "not found". Never catch
`Exception` without a comment saying why and what happens next (`BLE001`). Failures of an engine
are `ERROR`, `TIMEOUT` or `OOM` verdicts, never `FALSE`.

## 9. Security

Untrusted input is parsed with hardened parsers (PNML goes through `defusedxml`). No `shell=True`.
Subprocesses only in `infrastructure/docker_runner.py`, with fixed arguments. No secrets in the
repository (a hook scans for private keys).

Enforcement: ruff `S` (bandit rules), import-linter (subprocess confined), pre-commit hook,
`pip-audit` in CI.

## 10. Structured data contract
Everything the platform exchanges is JSON from pydantic models; the net is a canonical JSON
document with PNML as an alternative serialization (`docs/net-document.md`). Use
the shared types of `docs/json-contract.md` (result envelope, `ElementRef`, `Bound`, `Marking`,
`Page`, formula tree, trace) instead of a new shape; cite places and transitions by id; make
lists paginated and outputs deterministic; keep names and ids exactly as uploaded. Nothing
offered to the LLM returns the net itself in any format (ADR 0013, ADR 0015).

**One operation per endpoint** (ADR 0014): each analysis and each transformation has its own route,
request model and result model and does exactly one thing; never a bundle, never a list of
operations in a body. The route names the operation, not the tool; the engine is a parameter
(`auto` by default). Composition is the caller's job.

Enforcement: pydantic models are the single source; exported JSON Schemas are checked for
staleness; contract tests validate every tool result; a guard test forbids the net itself in LLM tools.

## 11. Conversations and the LLM
The chat workflow has rules of its own (ADR 0008, 0009, 0017); they are tested, not just agreed.

- **Only an engine produces a verdict.** A `verdict` event is built by a tool from an engine
  result, with the engine and its version; the agent never copies a verdict from the model's text.
  A non-answer (UNKNOWN, TIMEOUT, OOM, ERROR) is reported as such everywhere, including the UI and
  the report.
- **The LLM never reads the net.** Tools return facts through inspection, never the net in any
  format; a detector (`net_leak`) withholds a result that would hold one.
- **Untrusted text is data.** Names, ids, descriptions and messages are quoted in JSON strings or
  delimited blocks (escaped so they cannot be closed from inside), never concatenated into
  instructions. Tests keep a corpus of hostile names.
- **One module imports the provider SDK** (import-linter). Agent tests use the scripted double of
  the LLM port; the quality of the real model is measured in `bench/`, not in unit tests.
- **A run is event-sourced and resumable**: everything the model saw and did is in the log, and a
  lost run starts again from it. Budgets end a run visibly (`budget_exhausted`).
- **The event vocabulary is a contract.** Adding a kind is easy; changing one needs an ADR. The UI
  handles kinds with an exhaustive `switch`, so a new kind fails its build until it is shown.

## 12. Small, reversible changes

One concern per commit and per pull request. Conventional commit messages (`feat:`, `fix:`,
`refactor:`, `docs:`, `test:`, `chore:`). A change that alters the architecture updates
`docs/architecture.md` and, when it is a decision, adds an ADR in `docs/adr/`.

Enforcement: commit-msg hook (conventional commits); documentation synchronisation hook.
