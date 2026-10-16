import type { SessionEvent } from "../api/types";
import { VerdictBadge } from "./VerdictBadge";

/** One line of the conversation. Everything is shown as text; nothing is interpreted as HTML. */
export function EventItem({ event }: { readonly event: SessionEvent }) {
  switch (event.kind) {
    case "session_started":
      return (
        <article className="event goal">
          <h3>Goal</h3>
          <p className="text">{event.goal}</p>
          {event.description_id !== undefined && event.description_id !== null && (
            <small>
              Description given ({event.description_origin ?? "unknown origin"}):{" "}
              {event.description_id}
            </small>
          )}
        </article>
      );
    case "user_message":
      return (
        <article className="event user">
          <h3>You</h3>
          <p className="text">{event.text}</p>
        </article>
      );
    case "assistant_message":
      return (
        <article className="event assistant">
          <h3>Assistant (written by the language model)</h3>
          <p className="text">{event.text}</p>
        </article>
      );
    case "tool_call":
      return (
        <details className="event tool">
          <summary>Tool: {event.tool}</summary>
          <pre className="text">{event.arguments}</pre>
        </details>
      );
    case "tool_result":
      return (
        <details className={`event tool ${event.ok ? "" : "failed"}`}>
          <summary>
            Result of {event.tool}
            {event.ok ? "" : " (refused)"}
          </summary>
          <pre className="text">{event.content}</pre>
        </details>
      );
    case "property_proposed":
      return (
        <article className="event property">
          <h3>Property proposed: {event.formula.id}</h3>
          {event.formula.gloss !== "" && <p className="text">{event.formula.gloss}</p>}
          <small>logic: {event.formula.logic}</small>
          <details>
            <summary>Formula tree</summary>
            <pre className="text">{JSON.stringify(event.formula.ast, null, 2)}</pre>
          </details>
        </article>
      );
    case "check_submitted":
      return (
        <p className="event note">
          Check submitted ({event.formula_ids.join(", ")}), job {event.job_id}.
        </p>
      );
    case "verdict":
      return (
        <p className="event verdict-line">
          <VerdictBadge verdict={event} />
        </p>
      );
    case "question":
      return (
        <article className="event question">
          <h3>Question from the assistant</h3>
          <p className="text">{event.text}</p>
        </article>
      );
    case "answer":
      return (
        <article className="event user">
          <h3>Your answer</h3>
          <p className="text">{event.text}</p>
        </article>
      );
    case "budget_exhausted":
      return <p className="event note">The assistant stopped: budget reached ({event.budget}).</p>;
    case "session_error":
      return (
        <p className="event error" role="alert">
          Error ({event.code}): {event.message}
        </p>
      );
    case "run_finished":
      return <p className="event note">The assistant finished its turn ({event.reason}).</p>;
    case "description_proposed":
      return (
        <article className="event property">
          <h3>Description proposed by the assistant</h3>
          <p className="text">{event.text}</p>
          <small>Stored only if you accept it.</small>
        </article>
      );
    case "description_accepted":
      return <p className="event note">Description accepted and stored (origin: llm).</p>;
    case "counterexample_classified":
      return (
        <article className="event property">
          <h3>
            Counterexample of {event.formula_id} read as {event.classification.replaceAll("_", " ")}
          </h3>
          <p className="text">{event.explanation}</p>
          <small>The assistant's interpretation: it changes no verdict.</small>
        </article>
      );
    case "session_cancelled":
      return <p className="event note">Session cancelled.</p>;
  }
}
