import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SessionEvent } from "../api/types";
import { EventItem } from "./EventItem";

const formula = {
  id: "f1",
  logic: "state",
  gloss: "can it block?",
  origin: "llm",
  ast: { op: "deadlock" },
} as const;

const EVERY_KIND: readonly SessionEvent[] = [
  {
    kind: "session_started",
    net_id: "n",
    goal: "Is it safe?",
    description_id: "d1",
    description_origin: "user",
  },
  { kind: "user_message", text: "hello" },
  { kind: "assistant_message", source: "llm", text: "I looked at the net." },
  { kind: "tool_call", call_id: "c1", tool: "net_summary", arguments: "{}" },
  {
    kind: "tool_result",
    call_id: "c1",
    tool: "net_summary",
    ok: true,
    content: '{"status": "ok"}',
  },
  { kind: "property_proposed", formula, rationale: "" },
  { kind: "check_submitted", job_id: "j1", formula_ids: ["f1"] },
  {
    kind: "verdict",
    job_id: "j1",
    result_index: 0,
    formula_id: "f1",
    verdict: "UNKNOWN",
    engine: "itstools",
    engine_version: "3.2",
    has_trace: false,
  },
  { kind: "question", question_id: "q1", text: "Which lock?" },
  { kind: "answer", question_id: "q1", text: "the one named lock" },
  { kind: "budget_exhausted", budget: "steps" },
  { kind: "session_error", code: "llm_unavailable", message: "no model" },
  { kind: "run_finished", reason: "completed" },
  { kind: "description_proposed", proposal_id: "p1", text: "A lock shared by two processes." },
  { kind: "description_accepted", proposal_id: "p1", description_id: "d2" },
  { kind: "session_cancelled" },
];

describe("EventItem", () => {
  it("shows every kind of event as something", () => {
    for (const event of EVERY_KIND) {
      const { container, unmount } = render(<EventItem event={event} />);
      expect(container.textContent, event.kind).not.toBe("");
      unmount();
    }
  });

  it("labels the assistant's text as written by the language model", () => {
    render(
      <EventItem event={{ kind: "assistant_message", source: "llm", text: "FALSE, certainly" }} />,
    );
    expect(screen.getByText(/written by the language model/)).toBeInTheDocument();
  });

  it("shows a verdict with its words, its engine and its version, not by colour alone", () => {
    for (const verdict of ["TRUE", "FALSE", "UNKNOWN", "TIMEOUT", "OOM", "ERROR"] as const) {
      const { container, unmount } = render(
        <EventItem
          event={{
            kind: "verdict",
            job_id: "j",
            result_index: 0,
            formula_id: "f1",
            verdict,
            engine: "itstools",
            engine_version: "3.2",
            has_trace: false,
          }}
        />,
      );
      expect(container.textContent).toContain(verdict);
      expect(container.textContent).toContain("itstools 3.2");
      unmount();
    }
  });

  it("does not present UNKNOWN as FALSE", () => {
    render(
      <EventItem
        event={{
          kind: "verdict",
          job_id: "j",
          result_index: 0,
          formula_id: "f1",
          verdict: "UNKNOWN",
          engine: "e",
          engine_version: "1",
          has_trace: false,
        }}
      />,
    );
    expect(screen.queryByText(/does not hold/)).not.toBeInTheDocument();
    expect(screen.getByText(/undecided/)).toBeInTheDocument();
  });

  it("renders text from the net or the model as text, never as HTML", () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const { container } = render(
      <EventItem event={{ kind: "assistant_message", source: "llm", text: hostile }} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain(hostile);
  });

  it("flags a refused tool call and an error with an alert", () => {
    render(
      <EventItem
        event={{ kind: "tool_result", call_id: "c", tool: "get_element", ok: false, content: "{}" }}
      />,
    );
    expect(screen.getByText(/refused/)).toBeInTheDocument();
    render(<EventItem event={{ kind: "session_error", code: "x", message: "boom" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
});
