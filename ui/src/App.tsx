import { useEffect, useState } from "react";
import { type EngineInfo, fetchEngines } from "./api/client";

type EnginesState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly engines: readonly EngineInfo[] }
  | { readonly kind: "failed"; readonly message: string };

/** The root of the UI: for now it shows which engines the platform can run. */
export function App() {
  const [state, setState] = useState<EnginesState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchEngines({ signal: controller.signal })
      .then((engines) => setState({ kind: "ready", engines }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          kind: "failed",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>pn-llm-verif</h1>
      {state.kind === "loading" && <p>Loading engines…</p>}
      {state.kind === "failed" && <p role="alert">Cannot reach the API: {state.message}</p>}
      {state.kind === "ready" && (
        <ul aria-label="Engines">
          {state.engines.map((engine) => (
            <li key={engine.name}>
              {engine.name} {engine.version} — {engine.available ? "available" : "not installed"}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
