import { useEffect, useReducer, useState } from "react";
import { cancelSession, sendAnswer, sendMessage } from "../api/client";
import { followEvents, type StreamStatus } from "../api/sse";
import { addEvents, type EventLog, emptyLog, isLive, openQuestion, stateOf } from "../state/events";
import { Composer } from "./Composer";
import { EventItem } from "./EventItem";

/** Human wording of each state of a session. */
const STATE_TEXT = {
  queued: "waiting for a worker",
  running: "the assistant is working",
  waiting_for_user: "the assistant is waiting for your answer",
  idle: "the assistant finished; your turn",
  cancelled: "cancelled",
} as const;

/** The conversation of one session: live events, the composer, the open question, cancel. */
export function SessionView({
  sessionId,
  retryDelayMs = 1000,
}: {
  readonly sessionId: string;
  readonly retryDelayMs?: number;
}) {
  const [log, add] = useReducer(
    (current: EventLog, added: Parameters<typeof addEvents>[0]["added"]) =>
      addEvents({ log: current, added }),
    emptyLog,
  );
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    const controller = new AbortController();
    followEvents({
      sessionId,
      after: 0,
      signal: controller.signal,
      onEvent: (event) => add([event]),
      onStatus: setStatus,
      retryDelayMs,
    });
    return () => controller.abort();
  }, [sessionId, retryDelayMs]);

  const state = stateOf({ events: log.events });
  const question = state === "waiting_for_user" ? openQuestion({ events: log.events }) : undefined;

  return (
    <section aria-label="Conversation">
      <header className="session-header">
        <p role="status">
          Session {sessionId}: {STATE_TEXT[state]}
          {status === "reconnecting" && " (reconnecting...)"}
        </p>
        {isLive({ state }) && (
          <button type="button" onClick={() => cancelSession({ sessionId })}>
            Cancel
          </button>
        )}
      </header>
      <div className="feed">
        {log.events.map((stored) => (
          <EventItem key={stored.number} event={stored.event} />
        ))}
      </div>
      {question !== undefined && (
        <Composer
          label={`Answer: ${question.text}`}
          disabled={false}
          onSend={async ({ text }) => {
            await sendAnswer({ sessionId, questionId: question.question_id, text });
          }}
        />
      )}
      {question === undefined && state !== "cancelled" && (
        <Composer
          label="Your message"
          disabled={state !== "idle"}
          onSend={async ({ text }) => {
            await sendMessage({ sessionId, text });
          }}
        />
      )}
    </section>
  );
}
