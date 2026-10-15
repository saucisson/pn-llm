import { callApi, type Enveloped } from "./http";
import type { NetRegistration, Session, StoredEvent } from "./types";

/** Upload a net: PNML by default, a JSON net document when the file says so. */
export function registerNet({
  text,
  isJson,
}: {
  readonly text: string;
  readonly isJson: boolean;
}): Promise<NetRegistration> {
  return callApi<NetRegistration>({
    method: "POST",
    path: "/v1/nets",
    body: text,
    contentType: isJson ? "application/json" : "application/pnml+xml",
  });
}

/** Store a description of the system for a net and return its id. */
export async function addDescription({
  netId,
  text,
  isMarkdown,
}: {
  readonly netId: string;
  readonly text: string;
  readonly isMarkdown: boolean;
}): Promise<string> {
  const envelope = await callApi<Enveloped<{ readonly description_id: string }>>({
    method: "POST",
    path: `/v1/nets/${encodeURIComponent(netId)}/descriptions`,
    body: text,
    contentType: isMarkdown ? "text/markdown" : "text/plain",
  });
  return envelope.data.description_id;
}

/** Open a session on a net. */
export async function startSession({
  netId,
  descriptionId,
  goal,
}: {
  readonly netId: string;
  readonly descriptionId: string | undefined;
  readonly goal: string;
}): Promise<Session> {
  const envelope = await callApi<Enveloped<Session>>({
    method: "POST",
    path: "/v1/sessions",
    body: JSON.stringify({
      net_id: netId,
      goal,
      ...(descriptionId === undefined ? {} : { description_id: descriptionId }),
    }),
  });
  return envelope.data;
}

/** Send a message once the assistant has finished its turn. */
export async function sendMessage({
  sessionId,
  text,
}: {
  readonly sessionId: string;
  readonly text: string;
}): Promise<StoredEvent> {
  const envelope = await callApi<Enveloped<StoredEvent>>({
    method: "POST",
    path: `/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    body: JSON.stringify({ text }),
  });
  return envelope.data;
}

/** Answer the question the assistant is waiting on. */
export async function sendAnswer({
  sessionId,
  questionId,
  text,
}: {
  readonly sessionId: string;
  readonly questionId: string;
  readonly text: string;
}): Promise<StoredEvent> {
  const envelope = await callApi<Enveloped<StoredEvent>>({
    method: "POST",
    path: `/v1/sessions/${encodeURIComponent(sessionId)}/answers`,
    body: JSON.stringify({ question_id: questionId, text }),
  });
  return envelope.data;
}

/** Cancel a session. */
export async function cancelSession({
  sessionId,
}: {
  readonly sessionId: string;
}): Promise<Session> {
  const envelope = await callApi<Enveloped<Session>>({
    method: "POST",
    path: `/v1/sessions/${encodeURIComponent(sessionId)}/cancel`,
  });
  return envelope.data;
}

/** Store a description the assistant proposed: only the user's acceptance does it. */
export async function acceptDescription({
  sessionId,
  proposalId,
}: {
  readonly sessionId: string;
  readonly proposalId: string;
}): Promise<StoredEvent> {
  const envelope = await callApi<Enveloped<StoredEvent>>({
    method: "POST",
    path: `/v1/sessions/${encodeURIComponent(sessionId)}/description-proposals/${encodeURIComponent(proposalId)}/accept`,
  });
  return envelope.data;
}
