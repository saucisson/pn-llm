# 17. JSON on the wire; the LLM-facing rendering lives in the tool facade

Status: accepted. Refines ADR 0009 and ADR 0013.

## Context
The LLM reads tool results as tokens. The API answers with the shared JSON envelope
(`docs/json-contract.md`). That envelope carries fields that only matter to clients
(`schema_version`, `tool`, `elapsed_s`, `net_id` on every call), and lists of references repeat
their keys on every element (`{"id": ..., "name": ..., "kind": ...}`). Should the API offer a more
compact, LLM-oriented representation, for instance through a special `Accept` media type?

## Decision
1. **The API speaks JSON only.** There is no LLM-specific media type. One shape per concept stays
   the rule (ADR 0013): the schemas, the contract tests and the guard that keeps the net away from
   the LLM (ADR 0015) all rely on it. A second representation would double what is to maintain
   and test for every route.
2. **The tool facade renders for the LLM.** The facade of the chat workflow (ADR 0009) is the only
   consumer that is an LLM. It turns each JSON result into the text given to the model, with a
   deterministic function per tool:
   - it drops what the model does not need (`schema_version`, `tool`, `elapsed_s`, `net_id`) and
     always keeps `status`, `warnings`, `error` and `truncated`;
   - it may write homogeneous lists compactly (one line per element instead of repeated keys),
     provided ids and names are reproduced exactly (`CLAUDE.md`, domain rule 7) and truncation is
     explicit;
   - it quotes names and ids as JSON strings, never as free text or Markdown, because they are
     attacker-controlled data (ADR 0009, ADR 0011).
3. **The rendering is chosen by measurement.** At least these renderings are compared on the
   scenarios of `docs/evaluation.md`, as an ablation: raw JSON, trimmed JSON, compact lists. The
   criteria are the number of tokens and the quality of the model's answers. Until the comparison
   exists, the facade uses trimmed JSON, the least risky.
4. **What the model saw is what is logged.** Session events record the rendered text, so a run can
   be replayed and audited exactly (ADR 0008).
5. **A human-readable format is a client concern.** If a human client ever needs one, it is
   built on top of the JSON, not as a second server representation.

## Consequences
- The API stays simple and its tests do not depend on how a model reads results.
- The cost of the verbose envelope is paid only inside the facade, where it can be removed.
- Changing the rendering never changes the API or the stored data, only the facade and the
  evaluation of the agent.
