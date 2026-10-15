import type { SessionEvent, StoredEvent } from "./api/types";

/** Wrap an event as the API stores it. */
export function stored({
  number,
  event,
}: {
  readonly number: number;
  readonly event: SessionEvent;
}): StoredEvent {
  return { session_id: "s1", number, at: 1, event };
}

/** The wire form of an event in a server-sent event stream. */
export function frame({ event }: { readonly event: StoredEvent }): string {
  return `id: ${event.number}\nevent: ${event.event.kind}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** A streaming response that sends the given chunks, then closes. */
export function streamOf({ chunks }: { readonly chunks: readonly string[] }): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** A JSON response. */
export function json({
  body,
  status = 200,
}: {
  readonly body: unknown;
  readonly status?: number;
}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** What the API's own envelope looks like around a payload. */
export function enveloped({ data }: { readonly data: unknown }): unknown {
  return { schema_version: "1.0", status: "ok", data };
}
