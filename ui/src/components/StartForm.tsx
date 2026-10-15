import { type FormEvent, useState } from "react";
import { addDescription, registerNet, startSession } from "../api/client";
import { ApiError } from "../api/http";
import type { NetRegistration } from "../api/types";

/** A short sentence on what the platform understood of the uploaded net. */
function describe({ registration }: { readonly registration: NetRegistration }): string {
  const { summary } = registration;
  return `${summary.source_id}: ${summary.places} places, ${summary.transitions} transitions, ${summary.arcs} arcs (${summary.kind} net).`;
}

/** Wording of a refusal of the API, with where the fault is when it says so. */
function messageOf({ failure }: { readonly failure: unknown }): string {
  if (failure instanceof ApiError) {
    return failure.location === undefined
      ? failure.message
      : `${failure.message} (at ${failure.location})`;
  }
  return failure instanceof Error ? failure.message : String(failure);
}

/** The form that starts a session: the net, a description of the system, and the goal. */
export function StartForm({
  onStarted,
}: {
  readonly onStarted: (args: { readonly sessionId: string }) => void;
}) {
  const [registration, setRegistration] = useState<NetRegistration | undefined>(undefined);
  const [description, setDescription] = useState("");
  const [markdown, setMarkdown] = useState(false);
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  async function chooseNet(file: File | undefined) {
    setRegistration(undefined);
    setError(undefined);
    if (file === undefined) {
      return;
    }
    try {
      setRegistration(
        await registerNet({
          text: await file.text(),
          isJson: file.name.toLowerCase().endsWith(".json"),
        }),
      );
    } catch (failure: unknown) {
      setError(messageOf({ failure }));
    }
  }

  async function chooseDescription(file: File | undefined) {
    if (file !== undefined) {
      setDescription(await file.text());
      setMarkdown(file.name.toLowerCase().endsWith(".md"));
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (registration === undefined) {
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const netId = registration.net_id;
      const descriptionId =
        description.trim() === ""
          ? undefined
          : await addDescription({ netId, text: description, isMarkdown: markdown });
      const session = await startSession({ netId, descriptionId, goal: goal.trim() });
      onStarted({ sessionId: session.session_id });
    } catch (failure: unknown) {
      setError(messageOf({ failure }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="start-form">
      <h2>New conversation</h2>
      <label>
        Petri net (PNML, or a JSON net document)
        <input
          type="file"
          accept=".pnml,.xml,.json"
          onChange={(event) => chooseNet(event.target.files?.[0])}
        />
      </label>
      {registration !== undefined && (
        <p role="status" className="understood">
          Understood — {describe({ registration })}
        </p>
      )}
      <label>
        What does the system do? (optional, in your words)
        <textarea
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
            setMarkdown(false);
          }}
        />
      </label>
      <label>
        …or a text file (.txt, .md)
        <input
          type="file"
          accept=".txt,.md"
          onChange={(event) => chooseDescription(event.target.files?.[0])}
        />
      </label>
      <label>
        What do you want to know or verify?
        <textarea value={goal} onChange={(event) => setGoal(event.target.value)} required />
      </label>
      <button type="submit" disabled={busy || registration === undefined || goal.trim() === ""}>
        Start
      </button>
      {error !== undefined && <p role="alert">{error}</p>}
    </form>
  );
}
