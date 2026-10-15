import { errorOf } from "./http";
import type { StoredEvent } from "./types";

/** A server-sent event frame once parsed. */
export type SseFrame = { readonly id: number; readonly data: string };

/** Frames found in a buffer, and the unfinished text that follows them. */
export type ParsedFrames = { readonly frames: readonly SseFrame[]; readonly rest: string };

/**
 * Split a buffer into complete server-sent event frames.
 *
 * A frame ends with a blank line. Comments (heartbeats) and frames without an id are skipped.
 */
export function parseSseFrames({ buffer }: { readonly buffer: string }): ParsedFrames {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const block of blocks) {
    let id: number | undefined;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("id:")) {
        id = Number.parseInt(line.slice(3).trim(), 10);
      } else if (line.startsWith("data:")) {
        data.push(line.slice(5).trimStart());
      }
    }
    if (id !== undefined && !Number.isNaN(id) && data.length > 0) {
      frames.push({ id, data: data.join("\n") });
    }
  }
  return { frames, rest };
}

/** How the connection to the event stream is doing. */
export type StreamStatus = "connecting" | "live" | "reconnecting";

/**
 * Follow the events of a session until `signal` aborts.
 *
 * It reconnects by itself after a failure or a closed connection, resuming after the last event
 * received (`Last-Event-ID`), so no event is missed or shown twice by the server.
 */
export async function followEvents({
  sessionId,
  after,
  signal,
  onEvent,
  onStatus,
  retryDelayMs,
}: {
  readonly sessionId: string;
  readonly after: number;
  readonly signal: AbortSignal;
  readonly onEvent: (event: StoredEvent) => void;
  readonly onStatus: (status: StreamStatus) => void;
  readonly retryDelayMs: number;
}): Promise<void> {
  let last = after;
  while (!signal.aborted) {
    try {
      onStatus("connecting");
      const response = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/events`, {
        headers: { Accept: "text/event-stream", "Last-Event-ID": String(last) },
        signal,
      });
      if (!response.ok || response.body === null) {
        throw await errorOf({ response });
      }
      onStatus("live");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseSseFrames({ buffer });
        buffer = parsed.rest;
        for (const frame of parsed.frames) {
          if (frame.id > last) {
            last = frame.id;
            onEvent(JSON.parse(frame.data) as StoredEvent);
          }
        }
      }
    } catch {
      if (signal.aborted) {
        return;
      }
    }
    if (signal.aborted) {
      return;
    }
    onStatus("reconnecting");
    await new Promise<void>((resolve) => setTimeout(resolve, retryDelayMs));
  }
}
