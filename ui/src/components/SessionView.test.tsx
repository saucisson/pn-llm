import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionEvent } from "../api/types";
import { enveloped, frame, json, stored, streamOf } from "../test-helpers";
import { SessionView } from "./SessionView";

const started: SessionEvent = { kind: "session_started", net_id: "n", goal: "Is it safe?" };

type Call = { readonly url: string; readonly init: RequestInit };

/** An API whose event stream sends `events` once, then stays quiet (the client keeps waiting). */
function stubApi({ events }: { readonly events: readonly SessionEvent[] }) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/events")) {
        const chunks = events.map((event, index) =>
          frame({ event: stored({ number: index + 1, event }) }),
        );
        return streamOf({ chunks });
      }
      return json({ status: 202, body: enveloped({ data: {} }) });
    }),
  );
  return calls;
}

function view() {
  return render(<SessionView sessionId="s1" retryDelayMs={60_000} />);
}

describe("SessionView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the events as they arrive, with the state in words", async () => {
    stubApi({
      events: [
        started,
        { kind: "assistant_message", source: "llm", text: "Looking at the net." },
        {
          kind: "verdict",
          job_id: "j",
          result_index: 0,
          formula_id: "f1",
          verdict: "FALSE",
          engine: "itstools",
          engine_version: "3.2",
          has_trace: true,
        },
      ],
    });
    view();
    expect(await screen.findByText("Looking at the net.")).toBeInTheDocument();
    expect(screen.getByText(/Is it safe\?/)).toBeInTheDocument();
    expect(screen.getByText(/does not hold/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("the assistant is working");
  });

  it("links to the report of the session in both formats", async () => {
    stubApi({ events: [started] });
    view();
    expect(await screen.findByRole("link", { name: "Report (Markdown)" })).toHaveAttribute(
      "href",
      "/v1/sessions/s1/report?format=markdown",
    );
    expect(screen.getByRole("link", { name: "Report (JSON)" })).toHaveAttribute(
      "href",
      "/v1/sessions/s1/report",
    );
  });

  it("lets the user write only when the assistant has finished its turn", async () => {
    stubApi({ events: [started] });
    view();
    await screen.findByText(/Is it safe/);
    expect(screen.getByLabelText("Your message")).toBeDisabled();
  });

  it("sends a message when it is the user's turn", async () => {
    const calls = stubApi({ events: [started, { kind: "run_finished", reason: "completed" }] });
    view();
    const box = await screen.findByLabelText("Your message");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.setup().type(box, "And deadlocks?");
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/sessions/s1/messages")).toBe(true));
    const sent = calls.find((c) => c.url === "/v1/sessions/s1/messages");
    expect(JSON.parse(String(sent?.init.body))).toEqual({ text: "And deadlocks?" });
  });

  it("asks the open question and sends the answer", async () => {
    const calls = stubApi({
      events: [
        started,
        { kind: "question", question_id: "q1", text: "Which lock?" },
        { kind: "run_finished", reason: "waiting_for_user" },
      ],
    });
    view();
    const box = await screen.findByLabelText("Answer: Which lock?");
    await userEvent.setup().type(box, "the one named lock");
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/sessions/s1/answers")).toBe(true));
    const sent = calls.find((c) => c.url === "/v1/sessions/s1/answers");
    expect(JSON.parse(String(sent?.init.body))).toEqual({
      question_id: "q1",
      text: "the one named lock",
    });
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();
  });

  it("cancels the session on request and offers nothing once cancelled", async () => {
    const calls = stubApi({ events: [started] });
    const { unmount } = view();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.url === "/v1/sessions/s1/cancel")).toBe(true);
    unmount();

    stubApi({ events: [started, { kind: "session_cancelled" }] });
    view();
    await screen.findByText("Session cancelled.");
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();
  });

  it("offers to accept a proposed description, once", async () => {
    const calls = stubApi({
      events: [
        started,
        {
          kind: "description_proposed",
          proposal_id: "p1",
          text: "A lock shared by two processes.",
        },
        { kind: "run_finished", reason: "completed" },
      ],
    });
    view();
    const button = await screen.findByRole("button", { name: "Accept this description" });
    await userEvent.setup().click(button);
    await waitFor(() =>
      expect(calls.some((c) => c.url === "/v1/sessions/s1/description-proposals/p1/accept")).toBe(
        true,
      ),
    );
  });

  it("does not offer a description that was accepted", async () => {
    stubApi({
      events: [
        started,
        { kind: "description_proposed", proposal_id: "p1", text: "A lock." },
        { kind: "description_accepted", proposal_id: "p1", description_id: "d2" },
      ],
    });
    view();
    await screen.findByText(/Description accepted/);
    expect(
      screen.queryByRole("button", { name: "Accept this description" }),
    ).not.toBeInTheDocument();
  });

  it("shows why a message was refused", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/events")) {
          return streamOf({
            chunks: [
              frame({ event: stored({ number: 1, event: started }) }),
              frame({
                event: stored({ number: 2, event: { kind: "run_finished", reason: "completed" } }),
              }),
            ],
          });
        }
        return json({ status: 409, body: { detail: "The session is running" } });
      }),
    );
    view();
    const box = await screen.findByLabelText("Your message");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.setup().type(box, "x");
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The session is running");
  });
});
