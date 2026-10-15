# JSON contract

Rule (ADR 0013, ADR 0015): everything is structured JSON. The net has a canonical JSON document
(`docs/net-document.md`) and PNML is an alternative serialization chosen with `Accept` and
`Content-Type`. All shapes below are pydantic models in `app/domain`, frozen, named after the concept. JSON
Schemas are exported from them and committed. Examples are illustrative; the models are the
reference.

## Conventions
- Field names in `snake_case`, enums in lower case, except verdicts (TRUE, FALSE, UNKNOWN,
  TIMEOUT, OOM, ERROR, ADR 0006).
- Places and transitions are cited **by id**, never by position or by name alone. Ids and names
  come from the net as uploaded and are never normalized (`CLAUDE.md` rule 7).
- Outputs are deterministic: same input, same JSON, lists sorted by id unless stated.
- Lists that can be large are paginated. A response never silently drops data: it says how much
  exists and how to get the rest.
- A value that may be unknown says so with a tagged object, never with `null` or a magic number.
- Requests that fail validation, unknown ids or oversized input are HTTP errors in
  `application/problem+json` (RFC 9457). Expected outcomes of a tool (timeout, out of memory) are
  reported in the envelope (`status`, `error`), never as an HTTP error.
- Amounts of text are bounded: names longer than a limit are truncated with a flag.

## Shared types

`ElementRef` cites a place or a transition:
```json
{"id": "p12", "name": "crit1", "kind": "place"}
```

`Marking` is sparse (places holding no token are omitted):
```json
{"entries": [{"place": {"id": "p12", "name": "crit1", "kind": "place"}, "tokens": 1}]}
```

`Bound` is tagged:
```json
{"kind": "finite", "value": 1}
{"kind": "unbounded"}
{"kind": "unknown"}
```

`Page` request parameters are `limit` (default 50, maximum 500) and `cursor`; a truncated
response carries:
```json
{"returned": 50, "total": 1280, "next_cursor": "opaque"}
```

## Result envelope
Every analysis, inspection, reduction and check returns the same envelope around its own `data`:
```json
{
  "schema_version": "1.0",
  "tool": {"name": "analysis.invariants", "version": "0.3.0"},
  "net_id": "3c41c7d182377cd3",
  "status": "ok",
  "data": {},
  "warnings": [],
  "truncated": null,
  "error": null,
  "elapsed_s": 0.12
}
```
`status` is `ok`, `partial` (usable but incomplete, see `warnings`) or `failed` (`data` is null and
`error` is `{"code": "timeout", "message": "..."}`). `tool` is mandatory: every result names the
tool and the pinned version that produced it.

## Formulas
A formula is a syntax tree. Atoms cite ids; the platform validates them against the net.
```json
{
  "id": "f1",
  "logic": "ltl",
  "gloss": "The two processes are never in their critical section together.",
  "origin": "llm",
  "ast": {"op": "G", "arg": {"op": "not", "arg": {"op": "and", "args": [
    {"op": "tokens", "place": "p12", "cmp": ">=", "value": 1},
    {"op": "tokens", "place": "p22", "cmp": ">=", "value": 1}]}}}
}
```
- `logic`: `ltl`, `ctl` or `state` (a condition on one marking, checked for reachability).
- Operators: `not`, `and` and `or` (`args`, at least two), `implies` (`left`, `right`); LTL `G`,
  `F`, `X` (`arg`) and `U` (`left`, `right`); CTL `AG`, `AF`, `AX`, `EG`, `EF`, `EX` (`arg`) and
  `AU`, `EU` (`left`, `right`). Atoms: `tokens` (cardinality of one place: `place`, `cmp`,
  `value`), `compare` (cardinality of sums of places, `left` and `right` terms of kind `tokens`
  with `places`, or `const` with `value`), `enabled` (fireability: `transition`), `deadlock` and
  `const` (`value` true or false). `cmp` is one of `<`, `<=`, `==`, `!=`, `>=`, `>`.
- `origin` is `user`, `llm`, `template` or `mcc`.
- Text form for users and imports: `docs/formula-syntax.md`. `POST /v1/formulas/validate` takes
  `{"net_id", "formula"}` or `{"net_id", "text", "logic"?, "id"?, "gloss"?, "origin"?}` and
  answers with `valid`, the parsed `formula`, `errors` and `warnings` (each with `code`,
  `message` and a JSON `path`), the classes of atoms used (`atoms`), `uses_next` and the
  canonical `text`. The neXt operator is always reported as a warning: it limits the reductions
  that may be applied (`CLAUDE.md`, domain rule 3).
- `gloss` is the plain-language statement made by the proposer. It is shown to the user and
  audited against the tree for fidelity (`docs/evaluation.md`, M2).
- A check result records, for audit, the rendering sent to each engine (`rendered`: engine syntax
  as text). The rendering is produced by the adapter, never by the LLM.
- A formula cannot reference an unknown id: a check is rejected with 422, the `location` of the
  fault and the closest matches in `detail`; `validate` reports it as an error instead.

## Counterexamples
```json
{
  "formula_id": "f1",
  "initial_marking": {"entries": []},
  "steps": [{"transition": {"id": "t3", "name": "enter1", "kind": "transition"}}],
  "loop_start": null,
  "net_id": "3c41c7d182377cd3"
}
```
A trace always refers to the original net (`CLAUDE.md` domain rule 4). `loop_start` is the index
of the step where the cycle begins for an infinite counterexample. Replaying a trace
(`net.replay`) is done by the platform and returns whether it is valid and where it fails.

## Operations and endpoints
ADR 0014: **each analysis and each transformation has its own endpoint and does one thing**; the
endpoint is the operation, not the tool. Routes are under `/v1/nets/{net_id}`; the LLM facade
exposes one tool per row (ADR 0009), except "The net itself", which is for humans and clients:
no tool returns the net itself, in any format.

### The net itself
| Route | Purpose |
|---|---|
| `POST /v1/nets` | Register a net: JSON `NetDocument` (default) or PNML via `Content-Type`; identity is the canonical hash |
| `GET /v1/nets/{id}` | The `NetDocument` (default) or canonical PNML via `Accept`; never offered to the LLM |

### Inspection (reads, `GET`, synchronous)
| Route | Purpose | `data` |
|---|---|---|
| `/summary` | Size, net type, size category, initial token count | counts |
| `/places`, `/transitions` | Paginated lists, filter by name pattern or initial marking | `ElementRef` list |
| `/arcs` | Arcs with weights, filter by source or target | list of arcs |
| `/elements/{id}` | One element: name, input and output sets with weights, tokens | element detail |
| `/neighbourhood` | Elements within distance k of given ids, size-capped | sub-structure |
| `/search` | Elements whose name matches a pattern | `ElementRef` list |
| `/name-groups` | Families of indexed names (`fork_1` to `fork_5`) as pattern, range, count | list of groups |
| `/marking` | Non-zero initial marking | `Marking` |
| `/replay` (`POST`) | Replay a trace on the net | validity and failing step |
| `/description` | The user's text description (the only text document) | text with origin |

Implemented details: lists are paginated with `limit` (1 to 500, default 50) and an opaque
`cursor`; `truncated` is set exactly when more items exist. `/places` and `/transitions` filter by
`name` (glob `*`, `?`, case-sensitive); `/places` also by `marked`. `/search?q=` ignores case and
looks in names and ids. `/neighbourhood?ids=a&ids=b&depth=1&max_elements=100` ignores arc
direction, adds elements by distance then id, and sets `cut` when the cap stopped it (depth at
most 5, cap at most 500). `/name-groups` reports each family as `pattern` (numbers written `{}`),
`count`, one range per number (`min`, `max`, `distinct`, `width` when zero-padded) and an example.
`/summary` returns counts, the net kind, a size category and structural flags, never names.
Reference places and transitions are resolved: arcs always join real nodes.

### Descriptions (ADR 0011)
`POST /v1/nets/{id}/descriptions` (`text/plain` or `text/markdown`, `?origin=user|mcc|llm`, UTF-8,
stored exactly as sent, idempotent: 201 the first time, 200 after), `GET /v1/nets/{id}/descriptions`
and `GET /v1/descriptions/{id}` (one entry per net and origin). The id is a hash of the text.

### Sessions (ADR 0008)
`POST /v1/sessions` (`net_id`, optional `description_id`, `goal`) opens a session and queues the first
run. `POST /v1/sessions/{id}/messages` (409 unless the agent finished its turn),
`POST /v1/sessions/{id}/answers` (`question_id`, `text`; 409 unless a question is open, 422 for
another id), `POST /v1/sessions/{id}/cancel`, `GET /v1/sessions/{id}`. `GET /v1/sessions/{id}/events`
returns the events as JSON (`after`, `limit`) or, with `Accept: text/event-stream`, as server-sent
events (`id` is the event number, `event` its kind, `data` the `StoredEvent`), resumable with
`Last-Event-ID` or `after`; `follow=false` ends the stream when it is caught up.
`POST /v1/sessions/upload` (multipart: `net` file, `goal`, optional `description` text or
`description_file`) registers the net, stores the description and opens the session in one request.
`POST /v1/sessions/{id}/restart` (`with_description`) opens a new session with the same goal, with
or without the description, to compare conditions. A description proposed by the assistant
(`description_proposed`) is stored by `POST /v1/sessions/{id}/description-proposals/{proposal_id}/accept`.

### Analyses (`POST /analyses/{operation}`, one per operation)
| Operation | Result `data` |
|---|---|
| `p-invariants` | minimal-support P-invariants: weighted `ElementRef` lists |
| `t-invariants` | minimal-support T-invariants |
| `place-bounds` | `Bound` per place |
| `minimal-siphons` | sets of places |
| `minimal-traps` | sets of places |
| `dead-transitions` | transitions that can never fire (structurally decided) |
| `net-class` | classification flags (state machine, marked graph, free choice, ...) |
| `conflict-sets` | groups of transitions in structural conflict |
| `connected-components` | components, as `ElementRef` lists |

Each takes `{"engine": "auto", "limits": {...}, "parameters": {...}}` (parameters specific to the
operation, possibly empty), is deterministic, and is cached by net, operation, parameters and
tool version. Cheap operations answer `200` with the envelope; others answer `202` with a job
that follows the same lifecycle as checks (leases, cancellation, ADR 0003).

### Transformations (`POST /reductions/{rule}`, `POST /unfold`)
One route per reduction rule; each applies that one rule, to a fixpoint unless `max_applications`
is given. Planned rules: `fuse-series-places`, `fuse-series-transitions`, `fuse-parallel-places`,
`fuse-parallel-transitions`, `remove-self-loop-transitions`, `remove-implicit-places`,
`remove-dead-transitions`, `pre-agglomeration`, `post-agglomeration`. `POST /unfold` (colored nets,
M3) produces the equivalent P/T net.
```json
{"engine": "auto", "protected": ["p12", "p22", "t3"], "max_applications": null}
```
```json
{
  "rule": "fuse-series-places",
  "changed": true,
  "parent_id": "3c41c7d182377cd3",
  "new_net_id": "9a1f0e5c2b7d4e68",
  "applications": 4,
  "removed": [{"id": "p7", "name": "buffer_tmp", "kind": "place"}],
  "merged": [{"from": [{"id": "p5", "name": "stage_a", "kind": "place"},
                       {"id": "p6", "name": "stage_b", "kind": "place"}],
              "into": {"id": "p5", "name": "stage_a", "kind": "place"}}],
  "preserves": ["reachability_of_protected", "deadlock_freedom"]
}
```
When no application is possible, `changed` is `false`, `new_net_id` is `null` and no net is
created. The reduced net is stored by the platform; the LLM never receives it (ADR 0013).

### Catalog (`GET /operations`)
Lists every analysis and transformation with its route, parameters, result type and, for a
reduction, the properties it preserves, plus which engines are available for it.

`POST /v1/nets/{id}/replay` takes `{"steps": ["t1", ...], "initial_marking"?, "state_formula"?,
"page"?}`: it fires the transitions in order on a P/T net and returns `valid`, the number of firings
that succeeded (`replayed`), `failure` (the step, the transition and the places that lacked tokens),
the `final_marking`, a window of successive `markings` (`markings_from`, `markings_total`, the
envelope `truncated` carries the cursor) and, if a state condition was given, whether it holds on
the final marking (`state_formula_holds`).

### Verification (`POST /checks`, `GET /v1/jobs/{id}`)
Asynchronous verification of structured formulas (batch semantics, ADR 0014 point 7):
`check.submit` (`POST /v1/nets/{id}/checks`, 202), `check.get` (`GET /v1/jobs/{id}`), `check.cancel`
(`DELETE /v1/jobs/{id}`) and `check.trace` (`GET /v1/jobs/{id}/results/{k}/trace`: the counterexample
of the `k`-th result, steps citing transitions, on the original net). A result carries the engine,
its pinned version, the formula in the engine's syntax (`rendered`) and `trace_url` when there is a
counterexample.
