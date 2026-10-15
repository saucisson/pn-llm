# Architecture decision records

One short file per significant decision (context, decision, consequences), numbered in order.
Do not edit an accepted ADR to change the decision: add a new one that supersedes it.

| # | Decision |
|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](0002-onion-architecture-enforced-by-import-linter.md) | Onion architecture, enforced by import-linter |
| [0003](0003-sqlite-persistence.md) | SQLite for persistence |
| [0004](0004-engines-as-ephemeral-containers.md) | Engines run as ephemeral Docker containers |
| [0005](0005-immutable-content-addressed-nets.md) | Immutable, content-addressed nets |
| [0006](0006-verdicts-never-invented.md) | Verdicts are never invented |
| [0007](0007-code-style-rules.md) | Code style rules |
| [0008](0008-conversation-as-persisted-events.md) | A conversation is a persisted sequence of events (proposed) |
| [0009](0009-llm-behind-a-port.md) | The LLM is an outbound port with a scripted fake (proposed) |
| [0010](0010-text-only-chat-ui.md) | A text-only chat UI on a modern TypeScript stack (proposed) |
| [0011](0011-net-descriptions.md) | Net descriptions are stored by the API (proposed) |
| [0012](0012-evaluation-protocol-frozen-before-test.md) | The evaluation protocol is frozen before the test run (proposed) |
| [0013](0013-structured-json-contract.md) | Structured JSON everywhere; the LLM never reads PNML (proposed) |
| [0014](0014-one-endpoint-per-operation.md) | One endpoint per operation, independent of the tool (proposed) |
| [0015](0015-canonical-json-net-document.md) | A canonical JSON net document; PNML by content negotiation; identity by canonical hash (proposed) |
