import type { VerdictEvent } from "../api/types";

/** What each verdict means, in words: the badge never relies on colour alone. */
const MEANING: Record<VerdictEvent["verdict"], string> = {
  TRUE: "holds",
  FALSE: "does not hold",
  UNKNOWN: "undecided",
  TIMEOUT: "timed out",
  OOM: "out of memory",
  ERROR: "engine error",
};

/** The verdict an engine gave, with the engine and its version: the only source of verdicts. */
export function VerdictBadge({ verdict }: { readonly verdict: VerdictEvent }) {
  return (
    <span className={`verdict verdict-${verdict.verdict.toLowerCase()}`}>
      <strong>{verdict.verdict}</strong> {MEANING[verdict.verdict]}
      <small>
        {" "}
        — {verdict.formula_id}, engine {verdict.engine} {verdict.engine_version}
      </small>
    </span>
  );
}
