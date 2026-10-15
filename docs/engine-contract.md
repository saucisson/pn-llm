# Engine contract

Each engine is a Docker image whose **entrypoint** follows this contract. The API knows nothing
about tool-specific details: adapters live inside the image. The contract follows
`docs/json-contract.md` (ADR 0013): the net is given as PNML, rendered by the platform from the
canonical net document (ADR 0015); everything else is structured JSON.

**Status**: this is the target contract (version 1). The implemented version 0 reads `net.pnml`
and a `request.json` with plain-text formulas and writes a `result.json` without envelope; it is
migrated by the backlog (milestone M1).

## Inputs (mounted read-only in `/work/input/`)

- `net.pnml`: the net (P/T, or colored for engines that declare `supports_colored`), rendered
  deterministically from the stored net document, so it is the same PNML as `GET` with
  `Accept: application/pnml+xml`. The only non-JSON input. Engines needing another format convert
  it inside the image.
- `request.json`: a serialized engine request. Formulas are syntax trees whose atoms cite ids
  (the adapter renders the tool's own syntax and writes it to `rendered`, see below).

```json
{
  "schema_version": "1.0",
  "kind": "check",
  "net_id": "3c41c7d182377cd3",
  "formulas": [{"id": "f1", "logic": "ltl", "gloss": "...", "origin": "llm",
    "ast": {"op": "F", "arg": {"op": "tokens", "place": "p3", "cmp": ">=", "value": 1}}}],
  "limits": {"timeout_s": 300, "memory_mb": 4096}
}
```

`kind` is `check` (verify formulas), `analysis` or `reduction`. For the last two, `operation`
names the single operation to perform (for example `p-invariants` or `fuse-series-places`, ADR
0014) and `parameters` carries its options; a reduction also lists the `protected` element ids.
An engine declares in the registry the `operations` it can perform; the platform never sends it
another one.

## Output (written to `/work/output/`)

- `result.json`: the result envelope of `docs/json-contract.md`, with `data` as follows for a check.

```json
{
  "schema_version": "1.0",
  "tool": {"name": "itstools", "version": "x.y.z"},
  "net_id": "3c41c7d182377cd3",
  "status": "ok",
  "data": {"results": [
    {"id": "f1", "verdict": "FALSE", "time_s": 12.4, "rendered": "...",
     "trace": "trace_f1.json", "warnings": []}
  ]},
  "warnings": [],
  "truncated": null,
  "error": null,
  "elapsed_s": 12.4
}
```

- `trace_<id>.json`: a counterexample in the structured trace format (steps cite transition ids).

## Rules

- `verdict` is one of TRUE, FALSE, UNKNOWN, TIMEOUT, OOM, ERROR. When in doubt: UNKNOWN or ERROR,
  **never** FALSE.
- One entry per received formula, even when the whole run fails.
- `tool.version` is mandatory (the pinned version of the tool).
- Every id in the output exists in the input net; the platform rejects outputs that cite others.
- Output is deterministic JSON; no PNML or other XML in `result.json` or traces. The only other
  file an engine may write is `reduced.pnml` for a reduction that applied, with the element mapping
  in `result.json`; the platform imports it through its hardened PNML importer, hashes the result
  and stores it as a new net (ADR 0005, ADR 0015), and never shows it to the LLM.
- The container runs without network, with a read-only filesystem except `/work/output`.
- Traces refer to the net **as provided**; mapping back to the original net is done by the API.
