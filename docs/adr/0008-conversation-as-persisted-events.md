# 8. A conversation is a persisted sequence of events

Status: accepted

## Context
The user hands over a net and a description in a chat. The LLM works for a while, shows what it
does, reports intermediate results, and may ask the user a question. The user may close the page,
the API may run several processes (ADR 0003), and the work must be replayable and auditable.

## Decision
- A **session** belongs to one net (or none yet), optionally references a stored description
  (ADR 0011), starts with the user's goal as its first message, and is a strictly ordered sequence of **events**,
  stored in SQLite. Nothing about a conversation lives only in memory.
- A session starts with the user's **inputs**: the net (PNML), a **description of the system** in
  natural language (what the model represents, vocabulary, expected behaviour; optional but
  encouraged) and a **goal** (what the user wants to know or verify). They are recorded as the
  first event, `session_started`. The description belongs to the session, not to the net: nets are
  immutable and content-addressed (ADR 0005), and the same net can be described differently by
  different users. Description and goal are size-limited and are untrusted text like net names
  (ADR 0009).
- Events are frozen pydantic models in the domain, discriminated by `kind`. **Vocabulary, version 1
  (frozen):** `session_started`, `user_message`, `assistant_message`, `tool_call`, `tool_result`,
  `property_proposed`, `check_submitted`, `verdict`, `question`, `answer`, `budget_exhausted`,
  `session_error`, plus `run_finished` (the agent ended its turn: the user may write again) and
  `session_cancelled`. A `verdict` event carries the job id, the result index, the formula, the
  verdict, the engine and its version: it cannot be built without them.
- A **session run** is queued in the database like a check job (ADR 0018): a user message or an
  answer queues the run, a worker claims it with one atomic update and renews a lease while it
  works. The run is event-sourced (its state is the event log), so a run whose worker died is
  simply queued again.
- **Provenance is part of the event.** A `verdict` event references the job and result produced by
  an engine; the UI and the LLM can only show a verdict taken from such an event (ADR 0006).
  Text written by the LLM is always labelled as such.
- A `question` event moves the session to `waiting_for_user`; an `answer` event resumes it. The
  agent run is a job with a lease (like checks), so it survives a restart and can be cancelled.
- Clients follow a session through `GET /v1/sessions/{id}/events` (server-sent events, resumable
  with `Last-Event-ID`) reading from the database, never from process memory. SSE rather than
  WebSocket: the flow is one-way, commands are ordinary `POST`s, the event number is the resume
  token, and every reconnection can be served by any process.
- Text only for now: events carry no graphical information. Place and transition names are
  quoted as plain text, exactly as in the PNML.

## Consequences
- Any process can serve any session; a crash loses at most the event being written.
- Sessions are a complete log: they feed the evaluation (`bench/`) for free.
- The event vocabulary is a public contract; adding a kind is easy, changing one needs a new ADR.
