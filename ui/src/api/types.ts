import type { components } from "./schema";

type Schemas = components["schemas"];

/** A conversation about one net. */
export type Session = Schemas["Session"];
/** The states a session goes through, as the API names them. */
export type SessionState = Session["state"];
/** An event of a session with its number in the log. */
export type StoredEvent = Schemas["StoredEvent"];
/** One of the kinds of event, discriminated by `kind`. */
export type SessionEvent = StoredEvent["event"];
/** Answer to the upload of a net. */
export type NetRegistration = Schemas["NetRegistration"];
/** A verdict taken from an engine result. */
export type VerdictEvent = Extract<SessionEvent, { readonly kind: "verdict" }>;
/** A question of the assistant. */
export type QuestionEvent = Extract<SessionEvent, { readonly kind: "question" }>;
