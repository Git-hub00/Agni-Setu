/**
 * Minimal same-origin JSON client. Sessions are cookie-based (ADR-04); unsafe methods carry the
 * Django CSRF token from the `csrftoken` cookie in `X-CSRFToken`. Non-2xx responses become
 * ApiError; transport failures become NetworkError. Bodies are never logged.
 */

import { ApiError, NetworkError, type ApiErrorBody } from "./errors";

export const API_BASE = "/api/v1";

type UnsafeMethod = "POST" | "PUT" | "PATCH" | "DELETE";
type Method = "GET" | UnsafeMethod;

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Required for existing-resource mutations (If-Match precondition, API s.1). */
  ifMatch?: string;
  /** Stable idempotency key for commands (API s.1). */
  idempotencyKey?: string;
}

export interface ApiResponse<T> {
  status: number;
  data: T;
  etag: string | null;
}

export function readCookie(name: string, cookieSource: string = document.cookie): string | null {
  for (const part of cookieSource.split(";")) {
    const [rawKey, ...rest] = part.trim().split("=");
    if (rawKey === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  // Success envelopes are application/json; refusals are RFC 9457 application/problem+json.
  if (!/^application\/(problem\+)?json\b/i.test(contentType)) {
    return null;
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET") {
    const token = readCookie("csrftoken");
    if (token) {
      headers["X-CSRFToken"] = token;
    }
  }
  if (options.ifMatch) {
    headers["If-Match"] = options.ifMatch;
  }
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (cause) {
    throw new NetworkError(cause);
  }

  const data = await parseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, (data as ApiErrorBody | null) ?? null);
  }
  return { status: response.status, data: data as T, etag: response.headers.get("ETag") };
}
