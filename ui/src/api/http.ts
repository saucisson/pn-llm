/** Thrown when the API answers with an error status; carries the RFC 9457 problem. */
export class ApiError extends Error {
  readonly status: number;
  readonly location: string | undefined;

  constructor({
    status,
    detail,
    location,
  }: {
    readonly status: number;
    readonly detail: string;
    readonly location?: string | undefined;
  }) {
    super(detail);
    this.status = status;
    this.location = location;
  }
}

/** The fields of a problem+json body that the UI shows. */
type Problem = { readonly detail?: string; readonly location?: string };

/** Turn a failed response into an `ApiError` with whatever the problem body says. */
export async function errorOf({ response }: { readonly response: Response }): Promise<ApiError> {
  const problem = (await response.json().catch(() => ({}))) as Problem;
  return new ApiError({
    status: response.status,
    detail: problem.detail ?? response.statusText,
    location: problem.location,
  });
}

/** Call the API and return the parsed JSON body, or throw an `ApiError`. */
export async function callApi<T>({
  method,
  path,
  body,
  contentType,
  signal,
}: {
  readonly method: "GET" | "POST";
  readonly path: string;
  readonly body?: string;
  readonly contentType?: string;
  readonly signal?: AbortSignal;
}): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.body = body;
    init.headers = { "Content-Type": contentType ?? "application/json" };
  }
  if (signal !== undefined) {
    init.signal = signal;
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    throw await errorOf({ response });
  }
  return (await response.json()) as T;
}

/** A result envelope of the API: only `data` matters to the UI. */
export type Enveloped<T> = { readonly data: T };
