import { afterEach, describe, expect, it, vi } from "vitest";

import { readCookie, request } from "./client";
import { ApiError, NetworkError } from "./errors";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("returns parsed data and ETag for 2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }, { ETag: '"v1"' }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await request<{ ok: boolean }>("/things");

    expect(result.status).toBe(200);
    expect(result.data).toEqual({ ok: true });
    expect(result.etag).toBe('"v1"');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/things");
    expect(init.credentials).toBe("same-origin");
    expect(init.method).toBe("GET");
  });

  it("throws ApiError with status and body on 4xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(403, { code: "FORBIDDEN", message: "No" })));

    await expect(request("/things")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      code: "FORBIDDEN",
    });
    await expect(request("/things")).rejects.toBeInstanceOf(ApiError);
  });

  it("adds X-CSRFToken from the csrftoken cookie on unsafe methods only", async () => {
    document.cookie = "csrftoken=abc123";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, {}));
    vi.stubGlobal("fetch", fetchMock);

    await request("/commands", { method: "POST", body: { a: 1 }, idempotencyKey: "k-1", ifMatch: '"v3"' });
    const [, postInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const postHeaders = postInit.headers as Record<string, string>;
    expect(postHeaders["X-CSRFToken"]).toBe("abc123");
    expect(postHeaders["Content-Type"]).toBe("application/json");
    expect(postHeaders["Idempotency-Key"]).toBe("k-1");
    expect(postHeaders["If-Match"]).toBe('"v3"');
    expect(postInit.body).toBe(JSON.stringify({ a: 1 }));

    await request("/things");
    const [, getInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect((getInit.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  });

  it("wraps transport failures in NetworkError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("/things")).rejects.toBeInstanceOf(NetworkError);
  });

  it("reads cookies by name", () => {
    expect(readCookie("b", "a=1; b=two%20words; c=3")).toBe("two words");
    expect(readCookie("missing", "a=1")).toBeNull();
  });
});
