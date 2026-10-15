import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { streamOf } from "./test-helpers";

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamOf({ chunks: [] })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("offers to start a conversation", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "New conversation" })).toBeInTheDocument();
  });

  it("follows the session named by the address", () => {
    window.location.hash = "#/session/abc123";
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Session abc123");
    expect(screen.getByRole("link", { name: "New conversation" })).toBeInTheDocument();
  });
});
