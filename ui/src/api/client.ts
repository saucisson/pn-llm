import type { components } from "./schema";

/** An engine as reported by `GET /v1/engines`, typed from the OpenAPI document. */
export type EngineInfo = components["schemas"]["EngineInfo"];

/** Thrown when the API answers with an error status; carries the RFC 9457 problem text. */
export class ApiError extends Error {
  readonly status: number;

  constructor({ status, detail }: { readonly status: number; readonly detail: string }) {
    super(detail);
    this.status = status;
  }
}

/** Fetch the engines the platform knows, with their availability on this machine. */
export async function fetchEngines({
  signal,
}: {
  readonly signal?: AbortSignal;
}): Promise<readonly EngineInfo[]> {
  const response = await fetch("/v1/engines", signal === undefined ? {} : { signal });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as { readonly detail?: string };
    throw new ApiError({ status: response.status, detail: problem.detail ?? response.statusText });
  }
  const envelope = (await response.json()) as { readonly data: readonly EngineInfo[] };
  return envelope.data;
}
