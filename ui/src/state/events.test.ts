import { describe, expect, it } from "vitest";
import type { SessionEvent } from "../api/types";
import { stored } from "../test-helpers";
import { addEvents, emptyLog, isLive, openQuestion, stateOf } from "./events";

function log(...events: SessionEvent[]) {
  return events.map((event, index) => stored({ number: index + 1, event }));
}

const started: SessionEvent = { kind: "session_started", net_id: "n", goal: "g" };

describe("addEvents", () => {
  it("keeps events sorted and drops repeats", () => {
    const [one, two, three] = log(started, { kind: "user_message", text: "a" }, started);
    if (one === undefined || two === undefined || three === undefined) {
      throw new Error("fixture");
    }
    const first = addEvents({ log: emptyLog, added: [three, one] });
    const second = addEvents({ log: first, added: [two, one] });
    expect(second.events.map((e) => e.number)).toEqual([1, 2, 3]);
    expect(second.last).toBe(3);
  });

  it("returns the same log when nothing is new", () => {
    const [one] = log(started);
    if (one === undefined) {
      throw new Error("fixture");
    }
    const current = addEvents({ log: emptyLog, added: [one] });
    expect(addEvents({ log: current, added: [one] })).toBe(current);
  });
});

describe("stateOf", () => {
  it("follows the turns of the conversation", () => {
    expect(stateOf({ events: [] })).toBe("queued");
    expect(stateOf({ events: log(started) })).toBe("running");
    expect(stateOf({ events: log(started, { kind: "run_finished", reason: "completed" }) })).toBe(
      "idle",
    );
    expect(
      stateOf({
        events: log(
          started,
          { kind: "run_finished", reason: "completed" },
          { kind: "user_message", text: "x" },
        ),
      }),
    ).toBe("running");
    expect(
      stateOf({ events: log(started, { kind: "run_finished", reason: "waiting_for_user" }) }),
    ).toBe("waiting_for_user");
    expect(stateOf({ events: log(started, { kind: "run_finished", reason: "error" }) })).toBe(
      "idle",
    );
    expect(stateOf({ events: log(started, { kind: "session_cancelled" }) })).toBe("cancelled");
  });

  it("ignores the events that do not change the state", () => {
    expect(
      stateOf({
        events: log(
          started,
          { kind: "assistant_message", source: "llm", text: "t" },
          { kind: "budget_exhausted", budget: "steps" },
        ),
      }),
    ).toBe("running");
  });
});

describe("openQuestion", () => {
  const question: SessionEvent = { kind: "question", question_id: "q1", text: "Which?" };

  it("finds the question nobody answered", () => {
    expect(openQuestion({ events: log(started, question) })?.question_id).toBe("q1");
  });

  it("is empty once answered", () => {
    expect(
      openQuestion({
        events: log(started, question, { kind: "answer", question_id: "q1", text: "this" }),
      }),
    ).toBeUndefined();
  });

  it("is empty without a question", () => {
    expect(openQuestion({ events: log(started) })).toBeUndefined();
  });
});

describe("isLive", () => {
  it("is false only for a cancelled session", () => {
    expect(isLive({ state: "idle" })).toBe(true);
    expect(isLive({ state: "cancelled" })).toBe(false);
  });
});
