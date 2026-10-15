import type { QuestionEvent, SessionEvent, SessionState, StoredEvent } from "../api/types";

/** The events received so far, in order of number, without duplicates. */
export type EventLog = { readonly events: readonly StoredEvent[]; readonly last: number };

/** The empty log of a session whose events have not been read yet. */
export const emptyLog: EventLog = { events: [], last: 0 };

/** Add events to a log: sorted by number, each number kept once. */
export function addEvents({
  log,
  added,
}: {
  readonly log: EventLog;
  readonly added: readonly StoredEvent[];
}): EventLog {
  const known = new Set(log.events.map((stored) => stored.number));
  const fresh = added.filter((stored) => !known.has(stored.number));
  if (fresh.length === 0) {
    return log;
  }
  const events = [...log.events, ...fresh].sort((a, b) => a.number - b.number);
  return { events, last: events[events.length - 1]?.number ?? 0 };
}

/**
 * Where the session is, derived from its events alone: the last event that changes the state wins.
 *
 * Handling every kind with a `switch` makes the compiler refuse a new kind nobody handled here.
 */
export function stateOf({ events }: { readonly events: readonly StoredEvent[] }): SessionState {
  let state: SessionState = "queued";
  for (const stored of events) {
    state = nextState({ state, event: stored.event });
  }
  return state;
}

function nextState({
  state,
  event,
}: {
  readonly state: SessionState;
  readonly event: SessionEvent;
}): SessionState {
  switch (event.kind) {
    case "session_started":
    case "user_message":
    case "answer":
      return "running";
    case "run_finished":
      return event.reason === "waiting_for_user"
        ? "waiting_for_user"
        : event.reason === "cancelled"
          ? "cancelled"
          : "idle";
    case "session_cancelled":
      return "cancelled";
    case "assistant_message":
    case "tool_call":
    case "tool_result":
    case "property_proposed":
    case "check_submitted":
    case "verdict":
    case "question":
    case "budget_exhausted":
    case "session_error":
      return state;
  }
}

/** The question the assistant is waiting an answer for, if any. */
export function openQuestion({
  events,
}: {
  readonly events: readonly StoredEvent[];
}): QuestionEvent | undefined {
  const answered = new Set<string>();
  for (const stored of events) {
    if (stored.event.kind === "answer") {
      answered.add(stored.event.question_id);
    }
  }
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]?.event;
    if (event?.kind === "question" && !answered.has(event.question_id)) {
      return event;
    }
  }
  return undefined;
}

/** Tell whether the session still accepts work: it is not cancelled. */
export function isLive({ state }: { readonly state: SessionState }): boolean {
  return state !== "cancelled";
}
