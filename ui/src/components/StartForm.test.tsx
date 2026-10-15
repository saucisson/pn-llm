import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { enveloped, json } from "../test-helpers";
import { StartForm } from "./StartForm";

const REGISTRATION = {
  net_id: "n1",
  created: true,
  summary: { source_id: "mutex", kind: "pt", places: 3, transitions: 2, arcs: 6 },
};

type Call = { readonly url: string; readonly init: RequestInit };

function stubApi({ failNet = false }: { readonly failNet?: boolean } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (url === "/v1/nets") {
        return failNet
          ? json({ status: 422, body: { detail: "Invalid XML", location: "line 4" } })
          : json({ body: REGISTRATION });
      }
      if (url.endsWith("/descriptions")) {
        return json({ status: 201, body: enveloped({ data: { description_id: "d1" } }) });
      }
      return json({ status: 201, body: enveloped({ data: { session_id: "s9" } }) });
    }),
  );
  return calls;
}

describe("StartForm", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uploads the net, says what it understood, then starts the session", async () => {
    const calls = stubApi();
    const started: string[] = [];
    render(<StartForm onStarted={({ sessionId }) => started.push(sessionId)} />);
    const user = userEvent.setup();

    await user.upload(
      screen.getByLabelText(/Petri net/),
      new File(["<pnml/>"], "mutex.pnml", { type: "application/xml" }),
    );
    expect(
      await screen.findByText(/mutex: 3 places, 2 transitions, 6 arcs \(pt net\)/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled(); // no goal yet

    await user.type(
      screen.getByLabelText(/What does the system do/),
      "Two processes share a lock.",
    );
    await user.type(screen.getByLabelText(/What do you want to know/), "Is mutual exclusion kept?");
    await user.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => expect(started).toEqual(["s9"]));
    expect(calls.map((c) => c.url)).toEqual([
      "/v1/nets",
      "/v1/nets/n1/descriptions",
      "/v1/sessions",
    ]);
    expect(new Headers(calls[0]?.init.headers).get("Content-Type")).toBe("application/pnml+xml");
    expect(calls[1]?.init.body).toBe("Two processes share a lock.");
    expect(JSON.parse(String(calls[2]?.init.body))).toEqual({
      net_id: "n1",
      goal: "Is mutual exclusion kept?",
      description_id: "d1",
    });
  });

  it("does not store a description that is empty", async () => {
    const calls = stubApi();
    render(<StartForm onStarted={() => undefined} />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText(/Petri net/), new File(["{}"], "net.json"));
    await screen.findByText(/Understood/);
    await user.type(screen.getByLabelText(/What do you want to know/), "Any deadlock?");
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(calls.length).toBe(2));
    expect(calls.map((c) => c.url)).toEqual(["/v1/nets", "/v1/sessions"]);
    expect(new Headers(calls[0]?.init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(calls[1]?.init.body))).not.toHaveProperty("description_id");
  });

  it("shows where the net is wrong when the API refuses it", async () => {
    stubApi({ failNet: true });
    render(<StartForm onStarted={() => undefined} />);
    await userEvent.setup().upload(screen.getByLabelText(/Petri net/), new File(["<"], "bad.pnml"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid XML (at line 4)");
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("reads a description from a markdown file", async () => {
    const calls = stubApi();
    render(<StartForm onStarted={() => undefined} />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText(/Petri net/), new File(["<pnml/>"], "n.pnml"));
    await screen.findByText(/Understood/);
    await user.upload(screen.getByLabelText(/text file/), new File(["# Notes"], "notes.md"));
    await user.type(screen.getByLabelText(/What do you want to know/), "g");
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(calls.length).toBe(3));
    expect(new Headers(calls[1]?.init.headers).get("Content-Type")).toBe("text/markdown");
    expect(calls[1]?.init.body).toBe("# Notes");
  });
});
