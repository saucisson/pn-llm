import { afterEach, describe, expect, it, vi } from "vitest";
import { frame, stored, streamOf } from "../test-helpers";
import { followEvents, parseSseFrames } from "./sse";

const first = stored({ number: 1, event: { kind: "user_message", text: "one" } });
const second = stored({ number: 2, event: { kind: "user_message", text: "two" } });
const third = stored({ number: 3, event: { kind: "user_message", text: "three" } });

describe("parseSseFrames", () => {
  it("returns complete frames and keeps the unfinished tail", () => {
    const parsed = parseSseFrames({ buffer: `${frame({ event: first })}id: 2\ndata: {"par` });
    expect(parsed.frames.map((f) => f.id)).toEqual([1]);
    expect(parsed.rest).toBe('id: 2\ndata: {"par');
  });

  it("skips heartbeats and frames without an id", () => {
    const parsed = parseSseFrames({ buffer: ": keep-alive\n\ndata: lonely\n\n" });
    expect(parsed.frames).toEqual([]);
    expect(parsed.rest).toBe("");
  });

  it("joins the lines of a multi-line data field", () => {
    const parsed = parseSseFrames({ buffer: "id: 5\ndata: a\ndata: b\n\n" });
    expect(parsed.frames).toEqual([{ id: 5, data: "a\nb" }]);
  });
});

describe("followEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("delivers events, even when a frame is split between chunks", async () => {
    const text = frame({ event: first });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamOf({ chunks: [text.slice(0, 20), text.slice(20)] })),
    );
    const controller = new AbortController();
    const received: number[] = [];
    await followEvents({
      sessionId: "s1",
      after: 0,
      signal: controller.signal,
      onEvent: (event) => {
        received.push(event.number);
        controller.abort();
      },
      onStatus: () => undefined,
      retryDelayMs: 0,
    });
    expect(received).toEqual([1]);
  });

  it("reconnects after the connection closes and resumes after the last event", async () => {
    const calls: { readonly lastId: string | null }[] = [];
    const responses = [
      streamOf({ chunks: [frame({ event: first }), frame({ event: second })] }),
      streamOf({ chunks: [frame({ event: second }), frame({ event: third })] }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        calls.push({ lastId: new Headers(init.headers).get("Last-Event-ID") });
        return responses.shift() ?? streamOf({ chunks: [] });
      }),
    );
    const controller = new AbortController();
    const received: number[] = [];
    const statuses: string[] = [];
    await followEvents({
      sessionId: "s1",
      after: 0,
      signal: controller.signal,
      onEvent: (event) => {
        received.push(event.number);
        if (event.number === 3) {
          controller.abort();
        }
      },
      onStatus: (status) => statuses.push(status),
      retryDelayMs: 0,
    });
    expect(received).toEqual([1, 2, 3]); // the repeated event 2 is not delivered twice
    expect(calls.map((c) => c.lastId)).toEqual(["0", "2"]);
    expect(statuses).toContain("reconnecting");
    expect(statuses).toContain("live");
  });

  it("keeps trying after an error status", async () => {
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        attempts += 1;
        if (attempts === 1) {
          return new Response("{}", { status: 503 });
        }
        return streamOf({ chunks: [frame({ event: first })] });
      }),
    );
    const controller = new AbortController();
    const received: number[] = [];
    await followEvents({
      sessionId: "s1",
      after: 0,
      signal: controller.signal,
      onEvent: (event) => {
        received.push(event.number);
        controller.abort();
      },
      onStatus: () => undefined,
      retryDelayMs: 0,
    });
    expect(attempts).toBe(2);
    expect(received).toEqual([1]);
  });

  it("stops quietly when aborted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        init.signal?.throwIfAborted();
        return streamOf({ chunks: [] });
      }),
    );
    const controller = new AbortController();
    controller.abort();
    await followEvents({
      sessionId: "s1",
      after: 0,
      signal: controller.signal,
      onEvent: () => undefined,
      onStatus: () => undefined,
      retryDelayMs: 0,
    });
  });
});
