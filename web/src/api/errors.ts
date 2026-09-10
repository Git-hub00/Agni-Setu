/**
 * Typed API error envelope (docs/06_API_AND_EVENT_CONTRACTS.md s.1-2).
 * The server returns `{ code, message, details? }` for non-2xx responses; the client never logs
 * response bodies because they may contain applicant data.
 */

export interface ApiErrorBody {
  code?: string;
  message?: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.message ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get code(): string | undefined {
    return this.body?.code;
  }
}

/** Thrown when the request never produced an HTTP response (offline, DNS, aborted). */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Network request failed");
    this.name = "NetworkError";
    this.cause = cause;
  }
}
