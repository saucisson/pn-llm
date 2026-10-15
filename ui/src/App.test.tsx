import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

function answer({ status, body }: { readonly status: number; readonly body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the engines with their availability", async () => {
    answer({
      status: 200,
      body: {
        data: [
          {
            name: "dummy",
            version: "0.1",
            logics: ["ltl"],
            supports_colored: false,
            available: true,
          },
          {
            name: "tapaal",
            version: "tbd",
            logics: ["ctl"],
            supports_colored: true,
            available: false,
          },
        ],
      },
    });
    render(<App />);
    expect(await screen.findByText(/dummy 0.1 — available/)).toBeInTheDocument();
    expect(screen.getByText(/tapaal tbd — not installed/)).toBeInTheDocument();
  });

  it("says so when the API cannot be reached", async () => {
    answer({ status: 503, body: { detail: "down for maintenance" } });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("down for maintenance");
  });
});
